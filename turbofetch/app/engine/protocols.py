from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from turbofetch.app.utils.filename import (
    filename_from_url,
    parse_content_disposition,
    sanitize_filename,
)


@dataclass
class FileInfo:
    url: str
    final_url: str
    filename: str
    size: int = -1
    resumable: bool = False
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_type: Optional[str] = None
    content_disposition: Optional[str] = None


def parse_filename(content_disposition: Optional[str], url: str) -> str:
    name = parse_content_disposition(content_disposition)
    if not name:
        name = filename_from_url(url)
    return sanitize_filename(name)


def _parse_content_range_total(header: Optional[str]) -> int:
    if not header:
        return -1
    if "/" not in header:
        return -1
    total_part = header.split("/", 1)[1].strip()
    if total_part == "*" or not total_part.isdigit():
        return -1
    return int(total_part)


def _extract_file_info(
    original_url: str,
    final_url: str,
    status_code: int,
    headers: httpx.Headers,
) -> FileInfo:
    content_disp = headers.get("content-disposition")
    content_type = headers.get("content-type")
    etag = headers.get("etag")
    last_modified = headers.get("last-modified")
    accept_ranges = headers.get("accept-ranges", "").lower()
    content_range = headers.get("content-range")
    content_length = headers.get("content-length")
    transfer_encoding = headers.get("transfer-encoding", "").lower()

    size = -1
    if status_code == 206 and content_range:
        size = _parse_content_range_total(content_range)
    elif "chunked" not in transfer_encoding and content_length and content_length.isdigit():
        size = int(content_length)

    resumable = (
        status_code == 206
        or "bytes" in accept_ranges
        or bool(content_range)
    ) and size > 0

    filename = parse_filename(content_disp, final_url or original_url)
    return FileInfo(
        url=original_url,
        final_url=final_url,
        filename=filename,
        size=size,
        resumable=resumable,
        etag=etag,
        last_modified=last_modified,
        content_type=content_type,
        content_disposition=content_disp,
    )


def _is_loopback_url(url: str) -> bool:
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def build_client_kwargs(
    headers: Optional[dict[str, str]] = None,
    cookies: Optional[dict[str, str]] = None,
    proxy: Optional[str] = None,
    auth: Optional[tuple[str, str]] = None,
    timeout: int = 30,
    ssl_verify: bool = True,
    trust_env: Optional[bool] = None,
    url: str = "",
) -> dict:
    base_headers = {"Accept-Encoding": "identity"}
    if headers:
        base_headers.update(headers)
    if trust_env is None:
        resolved_trust_env = False if (proxy or _is_loopback_url(url)) else True
    else:
        resolved_trust_env = trust_env
    kwargs: dict = {
        "follow_redirects": True,
        "timeout": httpx.Timeout(connect=15.0, read=float(timeout), write=15.0, pool=15.0),
        "verify": ssl_verify,
        "trust_env": resolved_trust_env,
        "headers": base_headers,
    }
    if cookies:
        kwargs["cookies"] = cookies
    if proxy:
        kwargs["proxy"] = proxy
    if auth:
        kwargs["auth"] = httpx.BasicAuth(auth[0], auth[1])
    return kwargs


async def probe_url(
    url: str,
    headers: Optional[dict[str, str]] = None,
    cookies: Optional[dict[str, str]] = None,
    proxy: Optional[str] = None,
    auth: Optional[tuple[str, str]] = None,
    timeout: int = 30,
    ssl_verify: bool = True,
) -> FileInfo:
    client_kwargs = build_client_kwargs(
        headers=headers,
        cookies=cookies,
        proxy=proxy,
        auth=auth,
        timeout=timeout,
        ssl_verify=ssl_verify,
        url=url,
    )
    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            resp = await client.head(url)
            if resp.status_code in (405, 501) or resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "HEAD unsupported", request=resp.request, response=resp
                )
            info = _extract_file_info(url, str(resp.url), resp.status_code, resp.headers)
            if info.size <= 0 or not info.resumable:
                async with client.stream("GET", str(resp.url), headers={"Range": "bytes=0-0"}) as get_resp:
                    if get_resp.status_code in (200, 206):
                        range_info = _extract_file_info(
                            url,
                            str(get_resp.url),
                            get_resp.status_code,
                            get_resp.headers,
                        )
                        if range_info.size > 0 or range_info.resumable:
                            return range_info
            return info
        except httpx.HTTPError:
            async with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as get_resp:
                get_resp.raise_for_status()
                return _extract_file_info(
                    url,
                    str(get_resp.url),
                    get_resp.status_code,
                    get_resp.headers,
                )


def is_resume_valid(original_info: FileInfo, new_info: FileInfo) -> bool:
    if not new_info.resumable:
        return False
    if original_info.size > 0 and new_info.size > 0 and original_info.size != new_info.size:
        return False
    if original_info.etag and new_info.etag and original_info.etag != new_info.etag:
        return False
    if (
        original_info.last_modified
        and new_info.last_modified
        and original_info.last_modified != new_info.last_modified
    ):
        return False
    return True


async def validate_for_resume(
    url: str,
    original_info: FileInfo,
    headers: Optional[dict[str, str]] = None,
    cookies: Optional[dict[str, str]] = None,
    proxy: Optional[str] = None,
    auth: Optional[tuple[str, str]] = None,
    timeout: int = 30,
    ssl_verify: bool = True,
) -> tuple[bool, FileInfo]:
    new_info = await probe_url(
        url=url,
        headers=headers,
        cookies=cookies,
        proxy=proxy,
        auth=auth,
        timeout=timeout,
        ssl_verify=ssl_verify,
    )
    return is_resume_valid(original_info, new_info), new_info
