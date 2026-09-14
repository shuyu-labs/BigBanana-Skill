import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from bigbanana_project import normalize_script, resolve_shot_refs
from bigbanana_quality import assess

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

if __name__ == "__main__": unittest.main()
