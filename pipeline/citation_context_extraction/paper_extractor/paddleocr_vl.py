from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .heuristics import clean_doi, extract_metadata_from_text, extract_references_from_text, normalize_space, split_people
from .models import PaperMetadata, Reference


def load_paddleocr_vl_artifact(path: Path) -> tuple[PaperMetadata, list[Reference]]:
    with path.open(encoding="utf-8") as artifact_file:
        payload = json.load(artifact_file)
    return parse_paddleocr_vl_payload(payload)


def run_paddleocr_vl(
    pdf_path: Path,
    *,
    device: str | None = None,
    engine: str | None = None,
    vl_rec_backend: str | None = None,
    vl_rec_server_url: str | None = None,
    vl_rec_api_model_name: str | None = None,
    vl_rec_api_key: str | None = None,
    save_dir: Path | None = None,
) -> tuple[PaperMetadata, list[Reference], list[Path]]:
    if device and device.lower() == "cpu":
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
        _raise_if_gpu_paddle_without_cuda_device()
    if device and device.lower().startswith("gpu"):
        _raise_if_requested_gpu_is_unavailable(device)
    try:
        from paddleocr import PaddleOCRVL
    except ImportError as exc:
        raise RuntimeError(
            "PaddleOCR-VL mode requires paddleocr with PaddleOCRVL support, "
            "or --paddleocr-vl-json/--paddleocr-vl-command."
        ) from exc

    if device and device.lower() == "cpu":
        _force_paddle_cpu()
    init_kwargs = {
        "device": device,
        "engine": engine,
        "vl_rec_backend": vl_rec_backend,
        "vl_rec_server_url": vl_rec_server_url,
        "vl_rec_api_model_name": vl_rec_api_model_name,
        "vl_rec_api_key": vl_rec_api_key,
    }
    init_kwargs = {key: value for key, value in init_kwargs.items() if value}
    pipeline = PaddleOCRVL(**init_kwargs)
    try:
        try:
            prediction = pipeline.predict(input=str(pdf_path))
        except TypeError:
            prediction = pipeline.predict(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(_paddleocr_vl_runtime_hint(exc, device=device, engine=engine)) from exc

    pages = list(prediction) if not isinstance(prediction, list) else prediction
    if pdf_path.suffix.lower() == ".pdf" and hasattr(pipeline, "restructure_pages"):
        try:
            restructured = pipeline.restructure_pages(pages)
            pages = list(restructured) if not isinstance(restructured, list) else restructured
        except Exception:
            pass

    saved_files = _save_prediction_artifacts(pages, save_dir) if save_dir else []
    payload = _prediction_to_payload(pages)
    metadata, references = parse_paddleocr_vl_payload(payload)
    text = _collect_text(payload)
    if text:
        if not metadata.title:
            metadata = extract_metadata_from_text(text, source="paddleocr-vl")
            metadata.raw = payload
        if not references:
            references = extract_references_from_text(text, source="paddleocr-vl")
    return metadata, references, saved_files


def parse_paddleocr_vl_payload(payload: dict[str, Any]) -> tuple[PaperMetadata, list[Reference]]:
    metadata_payload = _first_mapping(payload, ["metadata", "paper", "document"]) or payload
    page_metadata = _metadata_from_layout_pages(payload)
    metadata = PaperMetadata(
        title=_first_string(metadata_payload, ["title", "paper_title", "name"]) or page_metadata.title,
        authors=split_people(metadata_payload.get("authors") or metadata_payload.get("author")) or page_metadata.authors,
        year=_coerce_year(metadata_payload.get("year") or metadata_payload.get("publication_year")),
        doi=clean_doi(_first_string(metadata_payload, ["doi", "DOI"])),
        abstract=_first_string(metadata_payload, ["abstract", "summary"]) or page_metadata.abstract,
        source="paddleocr-vl",
        confidence=float(metadata_payload.get("confidence", page_metadata.confidence or 0.75)),
        raw=metadata_payload,
    )
    references_payload = _first_list(payload, ["references", "bibliography", "reference_list"])
    references = [
        _reference_from_payload(item, index)
        for index, item in enumerate(references_payload)
        if isinstance(item, dict) or normalize_space(str(item))
    ]
    return metadata, references


def _metadata_from_layout_pages(payload: dict[str, Any]) -> PaperMetadata:
    blocks = _layout_blocks(payload)
    if not blocks:
        return PaperMetadata(source="paddleocr-vl")

    title_block = next(
        (
            block
            for block in blocks
            if block.get("block_label") == "doc_title" and normalize_space(block.get("block_content"))
        ),
        None,
    )
    title = normalize_space(title_block.get("block_content")) if title_block else None
    return PaperMetadata(
        title=title,
        authors=_authors_after_title(blocks, title_block),
        abstract=_abstract_from_blocks(blocks),
        source="paddleocr-vl",
        confidence=0.9 if title else 0.0,
    )


def _layout_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pages = payload.get("pages")
    if not isinstance(pages, list):
        pages = [payload]
    blocks: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_index = page.get("page_index", 0)
        for block in page.get("parsing_res_list") or []:
            if isinstance(block, dict):
                copied = dict(block)
                copied["_page_index"] = page_index
                blocks.append(copied)
    return sorted(
        blocks,
        key=lambda block: (
            block.get("_page_index") or 0,
            block.get("block_order") if block.get("block_order") is not None else 10**9,
            block.get("block_id") if block.get("block_id") is not None else 10**9,
        ),
    )


def _authors_after_title(blocks: list[dict[str, Any]], title_block: dict[str, Any] | None) -> list[str]:
    if title_block is None:
        return []
    try:
        title_index = blocks.index(title_block)
    except ValueError:
        return []

    author_names: list[str] = []
    for block in blocks[title_index + 1 : title_index + 8]:
        label = block.get("block_label")
        raw_content = str(block.get("block_content") or "")
        content = normalize_space(raw_content)
        if not content:
            continue
        if label in {"abstract", "paragraph_title", "doc_title"}:
            break
        names = _split_author_names(raw_content)
        if names:
            author_names.extend(names)
            continue
        if _looks_like_affiliation_or_email(content):
            continue
        if author_names:
            break

    authors: list[str] = []
    for name in author_names:
        if name not in authors:
            authors.append(name)
    return authors


def _split_author_names(text: str) -> list[str]:
    english_names = _split_english_author_lines(text)
    if english_names:
        return english_names
    cleaned = _strip_author_marks(text)
    japanese_names = re.findall(r"[\u3040-\u30ff\u3400-\u9fff々ー]{1,5}\s+[\u3040-\u30ff\u3400-\u9fff々ー]{1,8}", cleaned)
    if japanese_names:
        return [name for name in (normalize_space(name) for name in japanese_names) if name]
    return split_people(cleaned)


def _split_english_author_lines(text: str) -> list[str]:
    authors: list[str] = []
    for raw_line in text.splitlines():
        line = normalize_space(_strip_author_marks(raw_line))
        if not line:
            continue
        if _looks_like_affiliation_or_email(line):
            continue
        if not re.search(r"[A-Za-z]", line):
            continue
        if not re.fullmatch(r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'-]*(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'-]*)+", line):
            continue
        tokens = line.split()
        if len(tokens) >= 4 and len(tokens) % 2 == 0:
            candidates = [" ".join(tokens[index : index + 2]) for index in range(0, len(tokens), 2)]
        else:
            candidates = [line]
        for candidate in candidates:
            if candidate not in authors:
                authors.append(candidate)
    return authors


def _strip_author_marks(text: str) -> str:
    cleaned = re.sub(r"\$\s*\^\{[^}]+\}\s*\$", "  ", text)
    cleaned = re.sub(r"\^\{[^}]+\}", "  ", cleaned)
    cleaned = re.sub(r"\b\d+(?:,\d+)*\b", "  ", cleaned)
    cleaned = cleaned.replace("*", " ")
    return normalize_space(cleaned) or ""


def _looks_like_affiliation_or_email(text: str) -> bool:
    stripped = _strip_author_marks(text)
    lowered = stripped.lower()
    return "@" in lowered or "大学" in stripped or "university" in lowered


def _abstract_from_blocks(blocks: list[dict[str, Any]]) -> str | None:
    for block in blocks:
        if block.get("block_label") == "abstract":
            return normalize_space(block.get("block_content"))
    return None


def _reference_from_payload(item: Any, index: int) -> Reference:
    if not isinstance(item, dict):
        raw_text = normalize_space(str(item)) or ""
        return Reference(
            id=f"b{index}",
            raw_text=raw_text,
            source="paddleocr-vl",
            confidence=0.55,
        )
    raw_text = _first_string(item, ["raw_text", "text", "raw", "citation"]) or ""
    return Reference(
        id=str(item.get("id") or item.get("key") or f"b{index}"),
        raw_text=raw_text,
        title=_first_string(item, ["title", "paper_title"]),
        authors=split_people(item.get("authors") or item.get("author")),
        year=_coerce_year(item.get("year") or item.get("publication_year")),
        doi=clean_doi(_first_string(item, ["doi", "DOI"])),
        venue=_first_string(item, ["venue", "journal", "booktitle", "publisher"]),
        source="paddleocr-vl",
        confidence=float(item.get("confidence", 0.75)),
        raw=item,
    )


def _first_mapping(payload: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _first_list(payload: dict[str, Any], keys: list[str]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _first_string(payload: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized = normalize_space(value)
            if normalized:
                return normalized
    return None


def _coerce_year(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else text


def _prediction_to_payload(prediction: Any) -> dict[str, Any]:
    saved_json = _save_prediction_json(prediction)
    normalized = _normalize_prediction_value(prediction)
    if saved_json:
        return {
            "pages": saved_json,
            "raw": normalized,
            "text": _collect_text({"saved": saved_json, "raw": normalized}),
        }
    if isinstance(normalized, dict):
        if _has_extraction_keys(normalized):
            return normalized
        return {"raw": normalized, "text": _collect_text(normalized)}
    if isinstance(normalized, list):
        return {"pages": normalized, "text": _collect_text(normalized)}
    return {"raw": normalized, "text": normalize_space(str(normalized)) or ""}


def _save_prediction_json(prediction: Any) -> list[Any]:
    results = prediction if isinstance(prediction, list) else [prediction]
    json_payloads: list[Any] = []
    with tempfile.TemporaryDirectory(prefix="bibmgr-paddleocr-vl-json-") as temp_dir:
        output_dir = Path(temp_dir)
        for result in results:
            save_to_json = getattr(result, "save_to_json", None)
            if not callable(save_to_json):
                continue
            before = set(output_dir.glob("*.json"))
            save_to_json(save_path=output_dir)
            for json_path in sorted(set(output_dir.glob("*.json")) - before):
                try:
                    json_payloads.append(json.loads(json_path.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    continue
    return json_payloads


def _save_prediction_artifacts(prediction: Any, save_dir: Path) -> list[Path]:
    save_dir.mkdir(parents=True, exist_ok=True)
    before = _snapshot_files(save_dir)
    results = prediction if isinstance(prediction, list) else [prediction]
    for result in results:
        for method_name in ("save_to_json", "save_to_markdown"):
            method = getattr(result, method_name, None)
            if not callable(method):
                continue
            try:
                method(save_path=save_dir)
            except Exception:
                continue
    after = _snapshot_files(save_dir)
    return sorted(after - before)


def _snapshot_files(path: Path) -> set[Path]:
    if not path.exists():
        return set()
    return {item for item in path.rglob("*") if item.is_file()}


def _normalize_prediction_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_prediction_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_prediction_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    json_value = getattr(value, "json", None)
    if isinstance(json_value, dict):
        return _normalize_prediction_value(json_value)
    if callable(json_value):
        try:
            return _normalize_prediction_value(json_value())
        except TypeError:
            pass
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _normalize_prediction_value(to_dict())
    if hasattr(value, "__dict__"):
        return _normalize_prediction_value(vars(value))
    return str(value)


def _has_extraction_keys(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("metadata", "paper", "document", "references", "bibliography", "reference_list"))


def _collect_text(value: Any) -> str:
    parts: list[str] = []
    _collect_text_parts(value, parts)
    return "\n".join(part for part in parts if part)


def _collect_text_parts(value: Any, parts: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if lowered in {"text", "rec_text", "ocr_text", "content", "block_content"} and isinstance(item, str):
                for line in item.splitlines():
                    normalized = normalize_space(line)
                    if normalized:
                        parts.append(normalized)
                continue
            _collect_text_parts(item, parts)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text_parts(item, parts)


def _force_paddle_cpu() -> None:
    try:
        import paddle
    except ImportError:
        return
    set_device = getattr(paddle, "set_device", None)
    if callable(set_device):
        try:
            set_device("cpu")
        except Exception:
            return


def _raise_if_gpu_paddle_without_cuda_device() -> None:
    try:
        import paddle
    except ImportError:
        return
    is_compiled_with_cuda = getattr(paddle, "is_compiled_with_cuda", None)
    if not callable(is_compiled_with_cuda) or not is_compiled_with_cuda():
        return
    device_count = 0
    try:
        cuda = getattr(getattr(paddle, "device", None), "cuda", None)
        get_device_count = getattr(cuda, "device_count", None)
        if callable(get_device_count):
            device_count = int(get_device_count())
    except Exception:
        device_count = 0
    if device_count > 0:
        return
    raise RuntimeError(
        "PaddleOCR-VL CPU mode cannot run in this environment because the installed PaddlePaddle "
        "package is a GPU build and no CUDA-capable device is visible. Create a CPU Paddle environment "
        "for local CPU inference, for example: `uv pip uninstall paddlepaddle-gpu paddlepaddle` then "
        "`uv pip install paddlepaddle==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/` "
        "and `uv pip install -U 'paddleocr[doc-parser]'`. Alternatively use a GPU node or a VLM service."
    )


def _raise_if_requested_gpu_is_unavailable(device: str) -> None:
    try:
        import paddle
    except ImportError:
        return
    is_compiled_with_cuda = getattr(paddle, "is_compiled_with_cuda", None)
    if callable(is_compiled_with_cuda) and not is_compiled_with_cuda():
        raise RuntimeError(
            "PaddleOCR-VL GPU mode was requested, but the installed PaddlePaddle package is not a CUDA build. "
            "Install a GPU PaddlePaddle package that matches this node's CUDA version, then rerun with "
            f"`--paddleocr-vl-device {device}`."
        )
    device_count = 0
    try:
        cuda = getattr(getattr(paddle, "device", None), "cuda", None)
        get_device_count = getattr(cuda, "device_count", None)
        if callable(get_device_count):
            device_count = int(get_device_count())
    except Exception:
        device_count = 0
    if device_count <= 0:
        visible = os.environ.get("CUDA_VISIBLE_DEVICES")
        visible_text = f" CUDA_VISIBLE_DEVICES={visible!r}." if visible is not None else ""
        raise RuntimeError(
            "PaddleOCR-VL GPU mode was requested, but PaddlePaddle cannot see any CUDA-capable GPU."
            f"{visible_text} Run `nvidia-smi` on this node, request/allocate a GPU if this is a cluster job, "
            "and make sure CUDA_VISIBLE_DEVICES exposes at least one GPU before rerunning."
        )


def _paddleocr_vl_runtime_hint(exc: Exception, *, device: str | None, engine: str | None) -> str:
    message = str(exc)
    if _looks_like_cudnn_failure(message):
        selected_device = device or "auto/default GPU"
        selected_engine = engine or "paddlepaddle/default"
        return (
            "PaddleOCR-VL failed inside the GPU/cuDNN CV worker. "
            f"Selected device={selected_device}, engine={selected_engine}. "
            "This is usually an NVIDIA driver/CUDA/cuDNN/PaddlePaddle runtime issue, not a PDF parsing error. "
            "Try one of: add '--paddleocr-vl-device cpu' for a CPU fallback, add "
            "'--paddleocr-vl-engine transformers' if that stack is installed, or use a VLM service with "
            "'--vl-rec-backend vllm-server --vl-rec-server-url http://HOST:PORT/v1'. "
            f"Original error: {message}"
        )
    if _looks_like_cuda_device_failure(message):
        selected_device = device or "auto/default GPU"
        return (
            "PaddleOCR-VL failed because the installed PaddlePaddle runtime tried to use CUDA, "
            f"but no usable CUDA device was detected. Selected device={selected_device}. "
            "If you want CPU inference, install/use a CPU PaddlePaddle environment instead of a GPU Paddle build, "
            "or run with CUDA_VISIBLE_DEVICES='' and '--paddleocr-vl-device cpu'. "
            "For faster/stabler GPU inference, use a machine with a visible compatible NVIDIA GPU or a VLM service. "
            f"Original error: {message}"
        )
    return message


def _looks_like_cudnn_failure(message: str) -> bool:
    lowered = message.lower()
    return "cudnn" in lowered or "cudnn_status_execution_failed" in lowered


def _looks_like_cuda_device_failure(message: str) -> bool:
    lowered = message.lower()
    return (
        "cudaerrornodevice" in lowered
        or "no cuda-capable device" in lowered
        or "cuda error(100)" in lowered
    )
