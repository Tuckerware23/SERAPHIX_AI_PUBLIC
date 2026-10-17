"""Seraphix v2.9: read-only manuscript importer and paragraph-window scene retrieval.
Source manuscripts are NEVER written to. Local derived index lives in Memory/Book_Index.
"""
import json, re, hashlib, math
from pathlib import Path
from collections import Counter
from seraphix_config import SETTINGS
from datetime import datetime, timezone

STOP=set('the a an and or but of in on to for from with is are was were be been it its this that these those i you your me my we they he she his her their what who how why does do did tell explain about  book manuscript character chapter story please seraphix relationship between role development'.split())
INDEX=Path('Memory/Book_Index/active_manuscript_v29.json')

def tokenize(s):
    return [w for w in re.findall(r"[a-z0-9']+",s.lower()) if len(w)>2 and w not in STOP]

def _read(path):
    ext=path.suffix.lower()
    if ext=='.docx':
        from docx import Document
        doc=Document(str(path))
        return [(p.text.strip(),p.style.name if p.style else '') for p in doc.paragraphs if p.text.strip()]
    if ext=='.txt':
        return [(line.strip(),'') for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if ext=='.pdf':
        try: import pymupdf
        except ImportError as e: raise RuntimeError('PDF support needs: python -m pip install pymupdf') from e
        with pymupdf.open(str(path)) as pdf:
            return [(line.strip(),f'Page {page_num}') for page_num,page in enumerate(pdf,1) for line in page.get_text().splitlines() if line.strip()]
    raise ValueError('Choose a .docx, .txt or .pdf file')

def import_manuscript(source, base):
    source=Path(source).expanduser().resolve()
    if not source.is_file():raise FileNotFoundError(str(source))
    if source.suffix.lower() not in ('.docx','.txt','.pdf'):raise ValueError('Supported files: .docx, .txt, .pdf')
    blocks=_read(source)
    if not blocks:raise ValueError('No readable text found. Scanned image PDFs need OCR first.')
    chapter='Opening / unlabelled'
    paragraphs=[]
    for number,(content,style) in enumerate(blocks,1):
        if re.match(r'^\s*(?:chapter\s+(?:\d+|[ivxlcdm]+)|prologue|epilogue)\b',content,re.I) and len(content)<110 or (style.lower().startswith('heading') and len(content)<110):
            chapter=content[:100]
        paragraphs.append({'id':number,'chapter':chapter,'style':style,'text':content})
    index={'version':29,'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
           'indexed_at_utc':datetime.now(timezone.utc).isoformat(),'paragraphs':paragraphs}
    target=Path(base)/INDEX
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix('.tmp')
    tmp.write_text(json.dumps(index,ensure_ascii=False),encoding='utf-8')
    tmp.replace(target)
    return {'name':source.name,'paragraphs':len(paragraphs),'chapters':len(set(p['chapter'] for p in paragraphs)),'index':str(target)}

def retrieve_scene(question,base,max_scenes=4):
    path=Path(base)/INDEX
    if not path.is_file():return None,[]
    data=json.loads(path.read_text(encoding='utf-8'))
    ps=data['paragraphs']
    q=Counter(tokenize(question))
    if not q:return '',[]
    # Score contiguous windows (not isolated keyword chunks). Strongly reward character co-occurrence.
    names=[n for n in SETTINGS["entities"] if re.search(r'\b'+n+r'\b',question,re.I)]
    size=13; step=5
    windows=[]
    for i in range(0,len(ps),step):
        group=ps[i:min(i+size,len(ps))]
        if not group:continue
        joined=' '.join(p['text'] for p in group)
        t=Counter(tokenize(joined))
        overlap=sum((1+math.log(1+t[k])) for k in q if t[k])
        present=sum(bool(re.search(r'\b'+re.escape(n)+r'\b',joined,re.I)) for n in names)
        if names and present<len(names):overlap*=0.25
        else:overlap+=present*5
        if overlap>0:windows.append((overlap,i,group))
    windows.sort(key=lambda x:x[0],reverse=True)
    chosen=[]
    for score,i,group in windows:
        if any(abs(i-old_i)<size for old_i,_ in chosen):continue
        chosen.append((i,group))
        if len(chosen)>=max_scenes:break
    chosen.sort(key=lambda x:x[0])
    evidence=[]; snippets=[]
    for j,(i,group) in enumerate(chosen,1):
        label=f'Scene {j}'
        excerpt='\n'.join(f"(P{p['id']}) {p['text']}" for p in group)
        # preserve bounded context, not partial text per individual paragraph
        excerpt=excerpt[:6500]
        snippets.append(f'[{label}; {group[0]["chapter"]}; paragraphs {group[0]["id"]}-{group[-1]["id"]}]\n{excerpt}')
        evidence.append({'id':j,'chapter':group[0]['chapter'],'first':group[0]['id'],'last':group[-1]['id'],'text':excerpt})
    return '\n\n'.join(snippets),evidence
