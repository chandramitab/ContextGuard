import argparse,json
from collections import defaultdict
from pathlib import Path
from datasets import load_dataset
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"data/golden/redactionbench_20.jsonl"
def diverse(rows,count):
    g=defaultdict(list)
    for r in rows:g[r["category"]].append(r)
    cats=sorted(g);out=[];i=0
    while len(out)<count:
        hit=False
        for c in cats:
            if i<len(g[c]) and len(out)<count:out.append(g[c][i]);hit=True
        if not hit:break
        i+=1
    return out
def main():
    a=argparse.ArgumentParser();a.add_argument("--count",type=int,default=20);n=a.parse_args().count
    ds=load_dataset("RedactionBench/RedactionBench",split="test"); rows=diverse([dict(x) for x in ds],n);OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("w",encoding="utf8") as f:
        for i,r in enumerate(rows):f.write(json.dumps({"sample_id":f"rb_{i:03d}","raw_text":r["raw_text"],"spans":r["spans"],"category":r["category"],"genre":r["genre"],"is_synthetic":r["is_synthetic"],"original_document_url":r.get("original_document_url")},ensure_ascii=False)+"\n")
    print(f"Wrote {len(rows)} documents to {OUT}")
if __name__=="__main__":main()
