"""Bounded document extraction. PDF parsing runs in a disposable subprocess."""
import io
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_TEXT=200_000


def parse_file(filename,raw):
    suffix=Path(filename).suffix.lower()
    if suffix in ('.txt','.md'):
        text=raw.decode('utf-8-sig')
        if '\x00' in text: raise ValueError('文本包含非法字符，请使用 UTF-8 文本')
        pages=[(None,text)]
    elif suffix=='.docx':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist()
            if len(entries)>500 or sum(e.file_size for e in entries)>8*1024*1024:
                raise ValueError('Word 文档解压后过大')
            info=archive.getinfo('word/document.xml')
            if info.file_size>2*1024*1024: raise ValueError('Word 正文过大')
            xml=archive.read(info).decode('utf-8-sig')
        if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper(): raise ValueError('不支持带实体定义的文档')
        document=ElementTree.fromstring(xml)
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        pages=[(None,'\n'.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in document.findall('.//w:p',ns)))]
    elif suffix=='.pdf':
        if not raw.startswith(b'%PDF-'): raise ValueError('文件不是有效 PDF')
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw),strict=True)
        if reader.is_encrypted: raise ValueError('请上传未加密的 PDF')
        if len(reader.pages)>80: raise ValueError('单份 PDF 最多 80 页')
        pages=[]; length=0
        for index,page in enumerate(reader.pages):
            text=page.extract_text() or ''
            length+=len(text)
            if length>MAX_TEXT: raise ValueError('文档正文最多 20 万字')
            pages.append((index+1,text))
    else: raise ValueError('支持 TXT、Markdown、DOCX 和文字型 PDF')
    if sum(len(t) for _,t in pages)>MAX_TEXT: raise ValueError('文档正文最多 20 万字')
    if not any(text.strip() for _,text in pages): raise ValueError('未提取到文字；扫描件请先 OCR 后再上传')
    return pages


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError('文件最大 1 MiB')
        result={'pages':parse_file(sys.argv[1],raw)}
    except ImportError:
        result={'error':'PDF 解析依赖未安装，请在自己的 Conda 环境安装更新后的 requirements.txt'}
    except Exception:
        result={'error':'文档无法解析，可能已加密、格式损坏、超出限制或没有可提取文字；请转换为 UTF-8 TXT 重试'}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))
