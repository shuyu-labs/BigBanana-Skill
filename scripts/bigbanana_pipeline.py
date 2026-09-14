"""End-to-end BigBanana comic/drama production pipeline.

Stages: script -> asset prompts -> shot prompts -> images -> videos -> audio.
By default this command only creates a plan (safe review gate). Add --execute
to run generation; existing non-empty outputs are reused.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable

def run(args, check=True):
    cmd=[PYTHON, str(HERE/args[0]), *args[1:]]
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=check)

def write_plan(path, plan):
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Saved plan -> {path}")

def main():
    ap=argparse.ArgumentParser(description="BigBanana end-to-end comic/drama pipeline")
    ap.add_argument('--idea', required=True)
    ap.add_argument('--out-dir', default='bigbanana_project')
    ap.add_argument('--style', default='anime')
    ap.add_argument('--lang', default='中文')
    ap.add_argument('--duration', type=int, default=90)
    ap.add_argument('--chat-model', default='gpt-5.4')
    ap.add_argument('--image-model', default='gemini-3-pro-image-preview')
    ap.add_argument('--video-model', default='sora-2')
    ap.add_argument('--audio-model', default='gpt-audio-1.5')
    ap.add_argument('--execute', action='store_true', help='execute remote generation after writing plan')
    ap.add_argument('--skip-audio', action='store_true')
    ns=ap.parse_args(); out=Path(ns.out_dir).expanduser(); out.mkdir(parents=True, exist_ok=True)
    script=out/'script.json'; shots=out/'shots.json'; assets={k:out/f'assets_{k}.json' for k in ('character','scene','prop')}
    plan={'out_dir':str(out.resolve()),'models':{'chat':ns.chat_model,'image':ns.image_model,'video':ns.video_model,'audio':ns.audio_model},'files':{'script':str(script),'shots':str(shots),'assets':{k:str(v) for k,v in assets.items()}}}
    if not script.exists() or script.stat().st_size==0:
        run(['bigbanana_generate.py','script','--idea',ns.idea,'--duration',str(ns.duration),'--style',ns.style,'--lang',ns.lang,'--model',ns.chat_model,'--out',str(script)])
    for kind,p in assets.items():
        if not p.exists() or p.stat().st_size==0:
            run(['bigbanana_generate.py','asset-prompts','--script',str(script),'--kind',kind,'--model',ns.chat_model,'--out',str(p)])
    if not shots.exists() or shots.stat().st_size==0:
        run(['bigbanana_generate.py','shot-prompts','--script',str(script),'--model',ns.chat_model,'--out',str(shots)])
    data=json.loads(shots.read_text(encoding='utf-8')); shot_items=data.get('shots',[]) if isinstance(data,dict) else []
    plan['shot_count']=len(shot_items); plan['outputs']={'frames':[],'videos':[],'audio':[]}
    for i,s in enumerate(shot_items,1):
        sid=str(s.get('shot_id') or f'S{i:02d}').lower(); frame=out/f'{sid}_start.png'; video=out/f'{sid}.mp4'; audio=out/f'{sid}_vo.wav'
        plan['outputs']['frames'].append(str(frame)); plan['outputs']['videos'].append(str(video))
        if not ns.skip_audio and (s.get('dialogue') or s.get('narration')): plan['outputs']['audio'].append(str(audio))
        if ns.execute:
            refs=[]
            for apath in (assets['character'],assets['scene'],assets['prop']):
                try:
                    items=json.loads(apath.read_text(encoding='utf-8')).get('items',[])
                    refs += [str(out/f"{('char' if apath.name.endswith('character.json') else 'scene' if apath.name.endswith('scene.json') else 'prop')}_{j:02d}.png") for j,_ in enumerate(items,1)]
                except Exception: pass
            refs=[r for r in refs if Path(r).exists()][:4]
            if not frame.exists() or frame.stat().st_size==0:
                cmd=['bigbanana_image.py','generate','--prompt',s.get('start_frame_prompt',''),'--out',str(frame),'--model',ns.image_model,'--aspect','16:9']
                if refs: cmd += ['--ref', *refs]
                run(cmd)
            if not video.exists() or video.stat().st_size==0:
                run(['bigbanana_video.py','generate','--prompt',s.get('video_prompt',''),'--out',str(video),'--model',ns.video_model,'--start',str(frame),'--seconds',str(max(4,min(15,int(s.get('duration_seconds',8)))) )])
            text=(s.get('dialogue') or s.get('narration') or '').strip()
            if text and not ns.skip_audio and (not audio.exists() or audio.stat().st_size==0):
                run(['bigbanana_audio.py','generate','--text',text,'--out',str(audio),'--model',ns.audio_model,'--mode','dialogue' if s.get('dialogue') else 'narration'])
    write_plan(out/'pipeline_plan.json', plan)
    print(f"Pipeline {'executed' if ns.execute else 'planned'}: {len(shot_items)} shot(s).")

if __name__=='__main__': main()
