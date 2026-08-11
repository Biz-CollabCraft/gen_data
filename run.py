# ──────────────────────────────────────────────
# gen_data CLI 진입점 모듈
# ──────────────────────────────────────────────

import argparse
from daemon import run_forever


# ──────────────────────────────────────────────
# 메인 진입 함수
# ──────────────────────────────────────────────

def main():
    """gen_data 데몬 CLI 실행 인터페이스."""
    parser = argparse.ArgumentParser(description="gen_data 공유 타임라인 병렬 센서 데이터 시뮬레이터 데몬")
    parser.parse_args()

    run_forever()


if __name__ == "__main__":
    main()
