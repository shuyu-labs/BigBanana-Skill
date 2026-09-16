import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from bigbanana_project import normalize_script, resolve_shot_refs
from bigbanana_quality import assess
from bigbanana_visual import image_info, similarity
from PIL import Image

class OfflineTests(unittest.TestCase):
    def test_normalize_and_resolve_refs(self):
        root = Path(tempfile.mkdtemp())
        script = normalize_script({"characters":[{"name":"A"}],"scenes":[{"name":"Room"}],"props":[],"shots":[{"shot_id":"S01","characters":["A"],"scene":"Room"}]})
        (root / "character_01_A.png").write_bytes(b"x")
        (root / "scene_01_Room.png").write_bytes(b"x")
        refs = resolve_shot_refs(script, script["shots"][0], root)
        self.assertEqual(len(refs), 2)
        self.assertEqual(script["schema_version"], 2)

    def test_quality_returns_warning_for_missing_media(self):
        root = Path(tempfile.mkdtemp())
        script = normalize_script({"shots": [{"shot_id":"S01"}]})
        (root / "script.json").write_text(json.dumps(script), encoding="utf-8")
        (root / "shots.json").write_text(json.dumps({"shots": [{"shot_id":"S01","start_frame_prompt":"x","video_prompt":"y"}]}), encoding="utf-8")
        self.assertIn(assess(root)["grade"], {"warning", "fail"})

    def test_visual_similarity_and_blank_detection(self):
        root = Path(tempfile.mkdtemp())
        Image.new("RGB", (256, 256), (120, 80, 40)).save(root / "a.png")
        Image.new("RGB", (256, 256), (120, 80, 40)).save(root / "b.png")
        self.assertTrue(image_info(root / "a.png")["valid"])
        self.assertGreaterEqual(similarity(root / "a.png", root / "b.png"), 0.99)


class DirectorPipelineTests(unittest.TestCase):
    """Pure-logic ports from BigBanana-AI-Director directorAgentService.ts."""

    def test_split_source_preserves_every_char(self):
        from bigbanana_director import split_director_source
        text = "a" * 5000 + "\n" + "b" * 5000 + "\n" + "c" * 2000
        chunks = split_director_source(text, 6000)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(c) <= 6000 for c in chunks))

    def test_resolve_character_id_never_guesses_substring(self):
        from bigbanana_director import character_map, resolve_character_id
        script = {"characters": [{"id": "c1", "name": "周野"}, {"id": "c2", "name": "顾沉"}]}
        mapping = character_map(script)
        self.assertIsNone(resolve_character_id("小林", script, mapping))
        self.assertEqual(resolve_character_id("周野", script, mapping), "c1")

    def test_trim_dialogue_narration(self):
        from bigbanana_director import trim_dialogue_narration
        script = {"characters": [{"id": "c1", "name": "周野"}, {"id": "c2", "name": "顾沉"}]}
        self.assertEqual(trim_dialogue_narration("你没来过这里。顾沉查看记录", script), "你没来过这里。")
        self.assertEqual(trim_dialogue_narration("你没来过这里。随后他转身", script), "你没来过这里。随后他转身")

    def test_extract_fallback_dialogues_rejects_unknown_speaker(self):
        from bigbanana_director import extract_fallback_dialogues
        script = {
            "characters": [{"id": "c1", "name": "周野"}],
            "scenes": [{"id": "s1", "name": "巷口"}],
            "story_paragraphs": [{"text": "周野：你没来过这里。\n顾沉（画外）：我知道。", "sceneRefId": "s1"}],
        }
        lines = extract_fallback_dialogues(script)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["text"], "你没来过这里。")

    def test_enforce_beat_coverage_monotonic(self):
        from bigbanana_director import enforce_beat_coverage
        shots = [
            {"id": "shot-1", "sceneId": "s1", "actionSummary": "林夏走进房间", "beatId": "beat-2", "characters": [], "props": []},
            {"id": "shot-2", "sceneId": "s1", "actionSummary": "林夏在门口停下", "beatId": "beat-1", "characters": [], "props": []},
        ]
        beats = [
            {"id": "beat-1", "sceneId": "s1", "order": 1, "purpose": "setup", "sourceText": "林夏走进房间",
             "visibleAction": "林夏走进房间", "dialogueIds": [], "entryState": "", "exitState": ""},
            {"id": "beat-2", "sceneId": "s1", "order": 2, "purpose": "conflict", "sourceText": "林夏在门口停下",
             "visibleAction": "林夏在门口停下", "dialogueIds": [], "entryState": "", "exitState": ""},
        ]
        enforce_beat_coverage(shots, beats)
        self.assertEqual([s["beatId"] for s in shots], ["beat-1", "beat-2"])

    def test_sanitize_prop_bindings(self):
        from bigbanana_director import sanitize_prop_bindings
        script = {"scenes": [{"id": "s1"}, {"id": "s2"}], "props": [{"id": "p1", "name": "青铜罗盘"}]}
        shots = [
            {"id": "x1", "sceneId": "s1", "props": ["p1"], "actionSummary": "a"},
            {"id": "x2", "sceneId": "s2", "props": ["p1"], "actionSummary": "b"},
        ]
        beats = [{"id": "b1", "sceneId": "s2", "order": 1, "sourceText": "他掏出青铜罗盘",
                  "visibleAction": "掏出青铜罗盘", "dialogueIds": []}]
        sanitize_prop_bindings(shots, beats, script)
        self.assertEqual(shots[0]["props"], [])
        self.assertEqual(shots[1]["props"], ["p1"])

    def test_reconcile_dialogues_replaces_stale_ids(self):
        from bigbanana_director import reconcile_dialogues
        shots = [{"id": "shot-1", "sceneId": "s1", "dialogue": "她低声说：你终于来了",
                  "dialogueIds": ["stale"], "speakerCharacterId": "wrong", "characters": []}]
        dialogues = [{"id": "d1", "text": "你终于来了", "sceneId": "s1", "speakerName": "林夏", "speakerCharacterId": "c9"}]
        reconcile_dialogues(shots, dialogues)
        self.assertEqual(shots[0]["dialogueIds"], ["d1"])
        self.assertEqual(shots[0]["speakerCharacterId"], "c9")

    def test_allocate_shot_counts_respects_beat_minimum(self):
        from bigbanana_director import allocate_shot_counts
        scenes = [{"id": "s1"}, {"id": "s2"}]
        beats = [{"sceneId": "s1", "order": 1}, {"sceneId": "s1", "order": 2}, {"sceneId": "s2", "order": 3}]
        counts = allocate_shot_counts(scenes, beats, [], 4, [{"sceneId": "s1", "shotCount": 1}])
        self.assertGreaterEqual(sum(counts), 4)
        self.assertGreaterEqual(counts[0], 2)

if __name__ == "__main__": unittest.main()
