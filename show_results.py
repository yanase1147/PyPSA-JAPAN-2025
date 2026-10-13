"""保存済みの計算結果 (netCDF) を集計表とグラフで表示する

例:
    python show_results.py                                  # results/dispatch.nc の全期間・全国
    python show_results.py --area Tokyo                     # 需給バランスを東京エリアで (連系線の受送電込み)
    python show_results.py --start 2025-08-01 --end 2025-08-07   # 期間を絞る (31日以内は1時間値)
    python show_results.py --no-show                        # 画面に出さず PNG 保存のみ
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pypsa

from pypsa_japan import plots, print_summary, summarize


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nc", nargs="?", default="results/dispatch.nc", help="run_dispatch.py が出力した netCDF")
    ap.add_argument("--area", help="需給バランス図のエリア (省略時は全国)")
    ap.add_argument("--start", help="時系列図の開始日時 (例 2025-08-01)")
    ap.add_argument("--end", help="時系列図の終了日時 (その日を含む)")
    ap.add_argument("-o", "--out", default="results/figures", help="PNG の保存先フォルダ")
    ap.add_argument("--no-show", action="store_true", help="ウィンドウを開かず保存のみ")
    args = ap.parse_args()

    n = pypsa.Network(args.nc)
    if args.area and args.area not in plots.areas(n):
        ap.error(f"--area は次のいずれか: {', '.join(plots.areas(n))}")

    print_summary(summarize(n))

    plots.set_style()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    figs = {
        f"balance_{args.area or 'all'}": plots.plot_balance(n, args.area, args.start, args.end),
        "area_mix": plots.plot_area_mix(n),
        "price": plots.plot_price(n, args.start, args.end),
        "congestion": plots.plot_congestion(n),
    }
    for name, ax in figs.items():
        ax.figure.savefig(out / f"{name}.png", bbox_inches="tight")
    print(f"\n図を保存しました: {out.resolve()}")

    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
