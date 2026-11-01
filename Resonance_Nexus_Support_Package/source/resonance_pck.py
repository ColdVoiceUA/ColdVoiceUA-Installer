"""Streaming AKPK layout compatible with GameDub's existing full repack."""
import hashlib
from pathlib import Path
import struct

LIMIT = 128*1024*1024
CHUNK = 4*1024*1024

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(CHUNK),b''):h.update(block)
    return h.hexdigest()

def parse(path):
    path=Path(path);length=path.stat().st_size
    with path.open('rb') as f:
        prefix=f.read(64)
        if len(prefix)<28 or prefix[:4]!=b'AKPK':raise ValueError('Не Wwise AKPK/PCK.')
        endian=None
        for order in ('<','>'):
            values=struct.unpack_from(order+'5I',prefix,4)
            if 8<=values[0]<=LIMIT and values[1]<65536 and all(x<=LIMIT for x in values[2:]):endian=order;break
        if endian is None:raise ValueError('Невідомий endian AKPK.')
        header_size,flag,s1,s2,s3=values
        has_s4=s1+s2+s3+16<header_size
        s4=struct.unpack_from(endian+'I',prefix,24)[0] if has_s4 else 0
        pos=28 if has_s4 else 24
        if max(s1,s2,s3,s4)>LIMIT or pos+s1+s2+s3+s4>min(length,LIMIT):raise ValueError('Некоректні таблиці AKPK.')
        positions=[pos+s1,pos+s1+s2,pos+s1+s2+s3]
        tables=[]
        for size,start in zip((s2,s3,s4),positions):
            if size<4:tables.append([]);continue
            f.seek(start);section=f.read(size);count=struct.unpack_from(endian+'I',section)[0]
            if not count:tables.append([]);continue
            if (size-4)%count:raise ValueError('Некоректна таблиця AKPK.')
            es=(size-4)//count
            if es not in (20,24):raise ValueError('Непідтримуваний запис AKPK.')
            rows=[]
            for i in range(count):
                p=4+i*es;file_id,block=struct.unpack_from(endian+'II',section,p)
                payload_size=struct.unpack_from(endian+('I' if es==20 else 'Q'),section,p+8)[0]
                start_block,language=struct.unpack_from(endian+'II',section,p+(12 if es==20 else 16))
                rows.append({'file_id':file_id,'block':block,'size':payload_size,'offset':start_block*(block or 1),
                             'language':language,'entry_size':es,'size_pos':start+p+8,'start_pos':start+p+(12 if es==20 else 16)})
            tables.append(rows)
        if tables[0] or tables[2] or not tables[1]:raise ValueError('Очікується VO_MEDIA без bank/external payloads.')
        rows=tables[1];header_len=min(r['offset'] for r in rows if r['offset']>0)
        if header_len<pos+s1+s2+s3+s4 or header_len>LIMIT:raise ValueError('Некоректна межа payload.')
        keys=set();last=header_len
        for r in sorted(rows,key=lambda r:r['offset']):
            k=(r['language'],r['file_id'])
            if k in keys or r['offset']<last or r['size']<1 or r['offset']+r['size']>length:raise ValueError('Дубльовані/перекриті/обрізані media entries.')
            keys.add(k);last=r['offset']+r['size']
        f.seek(0);header=f.read(header_len)
    return {'endian':endian,'header':header,'entries':rows,'length':length}

def layout(info,replacements):
    keys={(r['language'],r['file_id']) for r in info['entries']}
    if set(replacements)-keys:raise ValueError('UA source ID відсутній в оригінальному PCK.')
    header=bytearray(info['header']);pos=len(header);result=[]
    for r in sorted(info['entries'],key=lambda r:r['offset']):
        block=r['block'] or 1;pos=((pos+block-1)//block)*block
        path=replacements.get((r['language'],r['file_id']));size=Path(path).stat().st_size if path else r['size']
        if size<1 or (r['entry_size']==20 and size>0xffffffff) or pos//block>0xffffffff:raise ValueError('Переповнення AKPK entry.')
        struct.pack_into(info['endian']+('I' if r['entry_size']==20 else 'Q'),header,r['size_pos'],size)
        struct.pack_into(info['endian']+'I',header,r['start_pos'],pos//block)
        result.append((r,pos,size,path));pos+=size
    return bytes(header),result,pos

def output_hash(original,info,replacements,write_to=None,progress=None):
    header,rows,length=layout(info,replacements);h=hashlib.sha256();position=0
    def push(data):
        nonlocal position
        h.update(data)
        if write_to:write_to.write(data)
        position+=len(data)
    with Path(original).open('rb') as source:
        push(header)
        for i,(r,offset,size,path) in enumerate(rows):
            padding=offset-position
            while padding:
                count=min(padding,CHUNK);push(bytes(count));padding-=count
            if path:
                with Path(path).open('rb') as stream:
                    for chunk in iter(lambda:stream.read(CHUNK),b''):push(chunk)
            else:
                source.seek(r['offset']);remaining=size
                while remaining:
                    chunk=source.read(min(CHUNK,remaining))
                    if not chunk:raise ValueError('Оригінальний PCK обрізаний.')
                    push(chunk);remaining-=len(chunk)
            if progress and i%1000==0:progress(i+1,len(rows))
    if position!=length:raise ValueError('PCK output length mismatch.')
    return h.hexdigest(),length

def payload_hash(path,row):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        f.seek(row['offset']);remaining=row['size']
        while remaining:
            data=f.read(min(remaining,CHUNK))
            if not data:raise ValueError('Обрізаний payload.')
            h.update(data);remaining-=len(data)
    return h.hexdigest()
