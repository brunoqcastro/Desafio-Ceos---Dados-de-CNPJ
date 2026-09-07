"""
Download automatico dos arquivos publicos do CNPJ (Receita Federal / SERPRO+).

O repositorio oficial (https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9)
e um compartilhamento publico do Nextcloud, organizado em pastas mensais (ex: 2026-08/)
contendo os arquivos zipados (Cnaes.zip, Empresas0.zip..Empresas9.zip,
Estabelecimentos0.zip..N.zip, Socios*.zip, Municipios.zip, etc).

Listamos e baixamos tudo via WebDAV (PROPFIND/GET), sem exigir que o usuario
navegue ou clique em nada manualmente.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin

import requests
from requests.auth import HTTPBasicAuth
from tqdm import tqdm

SHARE_TOKEN = "YggdBLfdninEJX9"
DAV_ROOT = f"https://arquivos.receitafederal.gov.br/public.php/dav/files/{SHARE_TOKEN}/"
AUTH = HTTPBasicAuth(SHARE_TOKEN, "")

NS = {"d": "DAV:"}

PROPFIND_BODY = b"""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype/>
    <d:getcontentlength/>
    <d:getlastmodified/>
  </d:prop>
</d:propfind>
"""

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 5


@dataclass
class DavEntry:
    name: str
    path: str  # caminho relativo dentro do share, ex: "2026-08/Cnaes.zip"
    is_dir: bool
    size: int


def propfind(path: str = "") -> list[DavEntry]:
    """Lista o conteudo (depth=1) de uma pasta do share via WebDAV."""
    url = urljoin(DAV_ROOT, path)
    resp = requests.request(
        "PROPFIND",
        url,
        auth=AUTH,
        data=PROPFIND_BODY,
        headers={"Depth": "1", "Content-Type": "application/xml"},
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    self_rel = path.rstrip("/")
    entries: list[DavEntry] = []
    for r in root.findall("d:response", NS):
        href = unquote(r.find("d:href", NS).text)
        rel = href.split(f"/public.php/dav/files/{SHARE_TOKEN}/", 1)[-1].rstrip("/")
        if rel == self_rel:
            continue  # entrada referente a propria pasta consultada

        propstat = r.find("d:propstat", NS)
        prop = propstat.find("d:prop", NS)
        is_dir = prop.find("d:resourcetype/d:collection", NS) is not None
        size_el = prop.find("d:getcontentlength", NS)
        size = int(size_el.text) if size_el is not None and size_el.text else 0

        entries.append(DavEntry(name=rel.rsplit("/", 1)[-1], path=rel, is_dir=is_dir, size=size))
    return entries


def find_latest_month(entries: list[DavEntry]) -> str:
    months = [e.name for e in entries if e.is_dir and re.fullmatch(r"\d{4}-\d{2}", e.name)]
    if not months:
        raise RuntimeError("Nenhuma pasta mensal (YYYY-MM) encontrada no compartilhamento.")
    return sorted(months)[-1]


def download_file(entry: DavEntry, dest_dir: Path, chunk_size: int = 1024 * 1024) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / entry.name

    if dest_path.exists() and dest_path.stat().st_size == entry.size:
        return dest_path  # ja baixado, nada a fazer

    url = urljoin(DAV_ROOT, entry.path)
    resume_from = dest_path.stat().st_size if dest_path.exists() else 0

    for attempt in range(1, MAX_RETRIES + 1):
        mode = "ab" if resume_from else "wb"
        headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
        try:
            with requests.get(url, auth=AUTH, headers=headers, stream=True, timeout=DEFAULT_TIMEOUT) as resp:
                if resp.status_code == 416:
                    break  # range invalido: arquivo local ja esta completo
                resp.raise_for_status()
                with open(dest_path, mode) as f, tqdm(
                    total=entry.size,
                    initial=resume_from,
                    unit="B",
                    unit_scale=True,
                    desc=entry.name,
                    leave=False,
                ) as bar:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        f.write(chunk)
                        bar.update(len(chunk))
            break
        except (requests.RequestException, OSError) as exc:
            wait = min(2**attempt, 30)
            print(
                f"  [aviso] falha ao baixar {entry.name} (tentativa {attempt}/{MAX_RETRIES}): {exc}. "
                f"Retentando em {wait}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
            resume_from = dest_path.stat().st_size if dest_path.exists() else 0
    else:
        raise RuntimeError(f"Nao foi possivel baixar {entry.name} apos {MAX_RETRIES} tentativas.")

    actual = dest_path.stat().st_size
    if actual != entry.size:
        raise RuntimeError(f"Tamanho incompativel para {entry.name}: esperado {entry.size}, obtido {actual}")
    return dest_path


def select_entries(entries: list[DavEntry], only: Optional[list[str]]) -> list[DavEntry]:
    files = [e for e in entries if not e.is_dir]
    if not only:
        return files
    only_lower = [o.lower() for o in only]
    return [e for e in files if any(e.name.lower().startswith(o) for o in only_lower)]


def write_manifest(dest_dir: Path, month: str, entries: list[DavEntry]) -> None:
    manifest = {"month": month, "files": [{"name": e.name, "size": e.size} for e in entries]}
    (dest_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Baixa os arquivos publicos do CNPJ (Receita Federal).")
    parser.add_argument("--dest", default="data/raw", help="Diretorio de destino (default: data/raw)")
    parser.add_argument("--month", default=None, help="Mes no formato YYYY-MM (default: mais recente disponivel)")
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Filtra por prefixo do nome do arquivo, ex: --only Cnaes Municipios Empresas0",
    )
    parser.add_argument("--list-only", action="store_true", help="Apenas lista os arquivos disponiveis, sem baixar")
    args = parser.parse_args()

    print("Consultando repositorio da Receita Federal (WebDAV)...")
    root_entries = propfind("")
    month = args.month or find_latest_month(root_entries)
    print(f"Mes selecionado: {month}")

    entries = propfind(f"{month}/")
    to_fetch = select_entries(entries, args.only)
    total_size = sum(e.size for e in to_fetch)
    print(f"{len(to_fetch)} arquivo(s) selecionado(s), total de {total_size / 1e9:.2f} GB")

    if args.list_only:
        for e in sorted(to_fetch, key=lambda x: x.name):
            print(f"  {e.name:30s} {e.size / 1e6:10.1f} MB")
        return

    dest_dir = Path(args.dest) / month
    for entry in to_fetch:
        print(f"Baixando {entry.name} ({entry.size / 1e6:.1f} MB)...")
        download_file(entry, dest_dir)

    write_manifest(dest_dir, month, to_fetch)
    print(f"Concluido. Arquivos em: {dest_dir.resolve()}")


if __name__ == "__main__":
    main()
