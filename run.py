"""CLI entrypoint for the FastAPI Source Data Producer control plane."""

import uvicorn

import config


# ──────────────────────────────────────────────
# 메인 진입 함수
# ──────────────────────────────────────────────

def main():
    uvicorn.run(
        "app.main:app",
        host=config.GEN_DATA_API_HOST,
        port=config.GEN_DATA_API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
