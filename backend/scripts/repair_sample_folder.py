"""修复桌面「周期报告样例_环比预览」：补 echarts 资源、重导 PDF、重生成交付总结。"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.convert_sample_html_to_pdf import _collect_html_files, html_to_pdf
from app.services.report_period_comparison_service import ensure_echarts_asset
from scripts.generate_delivery_deck import main as generate_deck_main

SAMPLE_DIR = Path.home() / "Desktop" / "周期报告样例_环比预览"


def repair_pdfs(folder: Path) -> None:
    html_files = [p for p in _collect_html_files(folder) if "环比样例" in p.name]
    for html_path in html_files:
        pdf_path = html_path.with_suffix(".pdf")
        print(f"PDF <- {html_path.name}")
        html_to_pdf(html_path, pdf_path)
        print(f"  -> {pdf_path.name} ({pdf_path.stat().st_size // 1024} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="修复样例目录图表与 PDF")
    parser.add_argument("--dir", type=Path, default=SAMPLE_DIR)
    parser.add_argument("--skip-deck", action="store_true")
    parser.add_argument("--skip-pdf", action="store_true")
    args = parser.parse_args()
    folder = args.dir
    if not folder.is_dir():
        raise SystemExit(f"目录不存在: {folder}")

    print(f"==> restore echarts: {folder / 'assets'}")
    ensure_echarts_asset(folder)

    if not args.skip_pdf:
        print("==> export PDFs")
        repair_pdfs(folder)

    if not args.skip_deck:
        print("==> delivery deck")
        quarterly = folder / "艾迪亚控股集团有限公司_季报_环比样例_20260401_V2.html"
        if not quarterly.is_file():
            quarterly = next(folder.glob("*_季报_*_V2.html"), None)
        if quarterly is None:
            print("WARN: 未找到季报 HTML，跳过交付总结")
        else:
            import sys

            sys.argv = [
                "repair",
                "--html-source",
                str(quarterly),
                "--out-html",
                str(folder / "艾迪亚控股集团有限公司_GEO交付总结报告.html"),
                "--out-pdf",
                str(folder / "艾迪亚控股集团有限公司_GEO交付总结报告.pdf"),
                "--tmp",
                str(folder / "_deck_charts"),
                "--no-pdf",
            ]
            generate_deck_main()

    print("REPAIR_OK")


if __name__ == "__main__":
    main()
