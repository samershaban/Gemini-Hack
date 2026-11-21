"""matplotlib charts for the README.

Colors follow one rule each: gray for the baselines we compare against, one blue for
our system's conditions. One axis per chart, recessive grid, values labeled at bar ends.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files, no window
import matplotlib.pyplot as plt

SURFACE_COLOR = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID_COLOR = "#e4e3df"
OUR_SYSTEM_COLOR = "#2a78d6"
BASELINE_COLOR = "#a3a29d"
BASELINE_CONDITIONS = ["random", "room_votes", "single_hydrogen_call"]


def style_axes(axes) -> None:
    axes.set_facecolor(SURFACE_COLOR)
    for side in ["top", "right"]:
        axes.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        axes.spines[side].set_color(GRID_COLOR)
    axes.tick_params(colors=TEXT_SECONDARY, labelsize=10)


def draw_accuracy_chart(accuracy_summary: dict, output_path: Path) -> None:
    """Horizontal bars: accuracy per condition, with the 33% chance line."""
    condition_names = [name for name, summary in accuracy_summary.items() if summary["accuracy"] is not None]
    if not condition_names:
        print("No accuracy numbers yet; skipping the accuracy chart")
        return
    condition_names.reverse()  # matplotlib draws the first bar at the bottom
    labels = [f"{accuracy_summary[name]['label']}  (n={accuracy_summary[name]['rounds']})" for name in condition_names]
    accuracies = [accuracy_summary[name]["accuracy"] * 100 for name in condition_names]
    colors = [BASELINE_COLOR if name in BASELINE_CONDITIONS else OUR_SYSTEM_COLOR for name in condition_names]

    figure, axes = plt.subplots(figsize=(8, 0.45 * len(condition_names) + 1.4), dpi=150)
    figure.patch.set_facecolor(SURFACE_COLOR)
    style_axes(axes)
    axes.barh(labels, accuracies, color=colors, height=0.6, edgecolor=SURFACE_COLOR, linewidth=2)
    axes.axvline(33.3, color=TEXT_SECONDARY, linestyle="--", linewidth=1)
    axes.text(33.3, len(condition_names) - 0.35, " chance (33%)", color=TEXT_SECONDARY, fontsize=9, va="bottom")
    for bar_position, accuracy in enumerate(accuracies):
        axes.text(accuracy + 1, bar_position, f"{accuracy:.0f}%", va="center", color=TEXT_PRIMARY, fontsize=9)
    axes.set_xlim(0, 105)
    axes.set_xlabel("Rounds where the lie was caught (%)", color=TEXT_SECONDARY)
    axes.xaxis.grid(True, color=GRID_COLOR, linewidth=0.8)
    axes.set_axisbelow(True)
    axes.set_title("Catching the lie: Poker Face vs. baselines", color=TEXT_PRIMARY, loc="left", fontsize=12)
    figure.tight_layout()
    figure.savefig(output_path, facecolor=SURFACE_COLOR)
    plt.close(figure)


def draw_calibration_chart(calibration_buckets: list[dict], output_path: Path) -> None:
    """Stated confidence vs. actual accuracy. Points on the diagonal = well calibrated."""
    filled_buckets = [bucket for bucket in calibration_buckets if bucket["rounds"] > 0]
    if not filled_buckets:
        print("No calibration data yet; skipping the calibration chart")
        return
    mean_confidences = [bucket["mean_confidence"] * 100 for bucket in filled_buckets]
    accuracies = [bucket["accuracy"] * 100 for bucket in filled_buckets]

    figure, axes = plt.subplots(figsize=(5.5, 5), dpi=150)
    figure.patch.set_facecolor(SURFACE_COLOR)
    style_axes(axes)
    axes.plot([0, 100], [0, 100], color=TEXT_SECONDARY, linestyle="--", linewidth=1, label="Perfectly calibrated")
    axes.plot(mean_confidences, accuracies, color=OUR_SYSTEM_COLOR, linewidth=2, marker="o", markersize=8,
              markeredgecolor=SURFACE_COLOR, markeredgewidth=2, label="Poker Face")
    for confidence, accuracy, bucket in zip(mean_confidences, accuracies, filled_buckets):
        axes.annotate(f"n={bucket['rounds']}", (confidence, accuracy), textcoords="offset points",
                      xytext=(6, 6), color=TEXT_SECONDARY, fontsize=8)
    axes.set_xlim(30, 100)
    axes.set_ylim(0, 100)
    axes.set_xlabel("How sure Gemini said it was (%)", color=TEXT_SECONDARY)
    axes.set_ylabel("How often it was right (%)", color=TEXT_SECONDARY)
    axes.grid(True, color=GRID_COLOR, linewidth=0.8)
    axes.set_axisbelow(True)
    axes.legend(frameon=False, labelcolor=TEXT_SECONDARY, fontsize=9, loc="upper left")
    axes.set_title("Does it know when it's guessing?", color=TEXT_PRIMARY, loc="left", fontsize=12)
    figure.tight_layout()
    figure.savefig(output_path, facecolor=SURFACE_COLOR)
    plt.close(figure)
