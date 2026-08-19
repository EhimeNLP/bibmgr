"""Development server entry point."""


def main() -> None:
    import uvicorn

    uvicorn.run("bibmgr_backend.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":  # pragma: no cover - console script is the normal path
    main()
