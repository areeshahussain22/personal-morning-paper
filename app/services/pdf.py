from __future__ import annotations

import base64
import ipaddress
import logging
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import Settings
from app.repositories.profile_repository import ProfileRepository

logger = logging.getLogger(__name__)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class PdfRenderer:
    def render(self, html: str, output_path: Path, base_url: str) -> None:
        raise NotImplementedError


class WeasyPrintRenderer(PdfRenderer):
    def render(self, html: str, output_path: Path, base_url: str) -> None:
        try:
            from weasyprint import HTML
        except Exception as exc:
            raise RuntimeError(
                "WeasyPrint is unavailable. On Windows install GTK3 from "
                "https://github.com/nickvidal/winlibs/blob/master/gtk3-runtime.zip, "
                "extract it, and add its bin directory to PATH; then restart PowerShell. "
                "On Ubuntu/Debian run: sudo apt install libpango-1.0-0 libpangoft2-1.0-0 "
                "libgdk-pixbuf-2.0-0 libcairo2. On macOS run: brew install pango libffi"
            ) from exc
        HTML(string=html, base_url=base_url).write_pdf(str(output_path))


class PlaywrightRenderer(PdfRenderer):
    def render(self, html: str, output_path: Path, base_url: str) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError("Playwright is unavailable; install playwright and run playwright install chromium") from exc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=str(output_path), format="A4", print_background=True, display_header_footer=True,
                     footer_template='<div style="font-size:9px;width:100%;text-align:center"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
                     margin={"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"})
            browser.close()


def choose_renderer(settings: Settings) -> PdfRenderer:
    if settings.pdf_renderer == "playwright":
        return PlaywrightRenderer()
    if settings.pdf_renderer == "weasyprint":
        return WeasyPrintRenderer()
    try:
        import weasyprint  # noqa: F401
        return WeasyPrintRenderer()
    except Exception:
        return PlaywrightRenderer()


def _public_ip(host: str) -> bool:
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    for address in addresses:
        parsed = ipaddress.ip_address(address)
        if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified or parsed.is_reserved:
            return False
        if parsed in ipaddress.ip_network("169.254.169.254/32"):
            return False
    return True


def fetch_image(url: str | None, settings: Settings, client: httpx.Client) -> str | None:
    if not url:
        return None
    current = url
    for _ in range(3):
        parsed = urlparse(current)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not _public_ip(parsed.hostname):
            return None
        try:
            response = client.get(current, follow_redirects=False)
        except httpx.HTTPError:
            return None
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return None
            current = urljoin(current, location)
            continue
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if response.status_code != 200 or not content_type.startswith("image/") or content_type == "image/svg+xml":
            return None
        if len(response.content) > settings.pdf_image_max_bytes:
            return None
        return f"data:{content_type};base64,{base64.b64encode(response.content).decode('ascii')}"
    return None


def _template_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).parents[1] / "templates"),
        autoescape=select_autoescape(["html"]),
    )


def _truncate(value: str | None, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    sentence = text[:limit].rsplit(". ", 1)[0].strip()
    if len(sentence) < limit // 2:
        sentence = text[:limit].rsplit(" ", 1)[0].strip()
    return sentence.rstrip(".,;: ") + "…"


def build_pdf(
    repo: ProfileRepository, user_id: str, edition_date: str, settings: Settings, force: bool = False
) -> Path:
    metadata = repo.edition_pdf_metadata(user_id, edition_date)
    if metadata is None:
        raise LookupError("Edition not found")
    output = Path("data/pdfs") / user_id / f"{edition_date}.pdf"
    if output.is_file() and not force:
        repo.set_pdf_status(metadata["edition_id"], "ready", str(output))
        return output
    key = f"{user_id}:{edition_date}"
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if output.is_file() and not force:
            return output
        repo.set_pdf_status(metadata["edition_id"], "running")
        started = time.perf_counter()
        edition = repo.render_edition(user_id, edition_date)
        if edition is None:
            repo.set_pdf_status(metadata["edition_id"], "failed")
            raise LookupError("Edition not found")
        env = _template_environment()
        env.filters["relative_time"] = lambda value: value or "recently"
        client = httpx.Client(timeout=settings.pdf_image_timeout_seconds)
        try:
            items = []
            for item in edition["render_items"]:
                item = dict(item)
                item["pdf_token"] = repo.get_or_create_token(
                    user_id, item["article_id"], edition["edition_id"], item["position"],
                    item.get("source_id", ""), "pdf"
                )
                item["image_src"] = fetch_image(item.get("image_url"), settings, client)
                item["source_url"] = f"{settings.public_base_url}/out/{item['pdf_token']}"
                item["headline"] = _truncate(item.get("headline"), 180)
                item["summary"] = _truncate(item.get("summary"), 520)
                items.append(item)
        finally:
            client.close()
        profile = repo.get_profile(user_id) or {}
        html = env.get_template("print.html").render(
            edition=edition, items=items, reader_name=profile.get("settings", {}).get("display_name") or profile.get("name", "Reader"),
            edition_number=sum(1 for item in repo.list_editions(user_id) if item["edition_date"] <= edition_date),
            public_base_url=settings.public_base_url,
            briefs=items[-3:] if len(items) > 8 else [],
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(".tmp")
        renderer = choose_renderer(settings)
        try:
            try:
                renderer.render(html, temp, settings.public_base_url)
            except RuntimeError:
                if settings.pdf_renderer != "auto" or not isinstance(renderer, WeasyPrintRenderer):
                    raise
                logger.warning("WeasyPrint failed; falling back to Playwright")
                PlaywrightRenderer().render(html, temp, settings.public_base_url)
            temp.replace(output)
        except Exception:
            if temp.exists():
                temp.unlink()
            repo.set_pdf_status(metadata["edition_id"], "failed")
            raise
        repo.set_pdf_status(metadata["edition_id"], "ready", str(output))
        logger.info("PDF rendered in %dms", int((time.perf_counter() - started) * 1000))
        return output
