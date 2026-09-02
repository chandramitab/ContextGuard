import json,textwrap
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];INP=ROOT/"data/golden/redactionbench_20.jsonl";OUT=ROOT/"data/rendered"
def getfont():
    p=Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(str(p),24) if p.exists() else ImageFont.load_default()
def main():
    if not INP.exists():raise SystemExit("Run bootstrap_redactionbench.py first")
    OUT.mkdir(parents=True,exist_ok=True);font=getfont();manifest=[]
    for line in INP.read_text(encoding="utf8").splitlines():
        r=json.loads(line);lines=textwrap.wrap(" ".join(r["raw_text"].split()),76);paths=[]
        for page,start in enumerate(range(0,len(lines),40),1):
            im=Image.new("RGB",(1200,1600),"white");d=ImageDraw.Draw(im);y=80
            for t in lines[start:start+40]:d.text((80,y),t,fill="black",font=font);y+=34
            p=OUT/f'{r["sample_id"]}_p{page}.png';im.save(p);paths.append(str(p.relative_to(ROOT)))
        manifest.append({"sample_id":r["sample_id"],"pages":paths})
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf8");print(f"Rendered {len(manifest)} docs")
if __name__=="__main__":main()
