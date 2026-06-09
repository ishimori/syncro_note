#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
開発アクティビティ図: git のコミットを「1時間ごと（JST）」に集計して棒グラフ化する。

- 横軸 = 1時間スロット（対象日 × 24時間）。曜日・日付ラベル付き。
- JST は epoch(UTC) + 9h で算出（TZ環境に依存しない）。
- 出力: images/commit_activity.png（紹介スライドが取り込む）。

使い方:  python build_commit_chart.py
"""
import os
import subprocess
import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
OUT = os.path.join(HERE, 'images', 'commit_activity.png')

NAVY = '#1E3A8A'
GOLD = '#F59E0B'
GOLD_HI = '#FBBF24'
INK = '#334155'
MUTE = '#94A3B8'
BAND = '#F1F5F9'

plt.rcParams['font.sans-serif'] = ['Meiryo', 'Yu Gothic', 'MS Gothic', 'sans-serif']
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

JST = datetime.timezone(datetime.timedelta(hours=9))
JPW = '月火水木金土日'  # weekday(): Mon=0 .. Sun=6


def commit_times():
    raw = subprocess.check_output(['git', 'log', '--pretty=format:%at'], cwd=REPO)
    epochs = [int(x) for x in raw.decode().split()]
    return [datetime.datetime.fromtimestamp(e, JST) for e in epochs]


def main():
    times = commit_times()
    total = len(times)
    days = sorted({t.date() for t in times})

    counts = {}
    for t in times:
        counts[(t.date(), t.hour)] = counts.get((t.date(), t.hour), 0) + 1

    xs, heights = [], []
    for di, d in enumerate(days):
        for h in range(24):
            xs.append(di * 24 + h)
            heights.append(counts.get((d, h), 0))
    peak = max(heights)

    fig, ax = plt.subplots(figsize=(15, 5.0), dpi=150)

    # 日ごとの背景バンド（交互）
    for di, d in enumerate(days):
        if di % 2 == 1:
            ax.axvspan(di * 24 - 0.5, di * 24 + 23.5, color=BAND, zorder=0)
        if di > 0:
            ax.axvline(di * 24 - 0.5, color=MUTE, lw=0.8, ls=(0, (4, 4)), zorder=1)

    bars = ax.bar(xs, heights, width=0.82, color=NAVY, zorder=3)
    for b, hgt in zip(bars, heights):
        if hgt == peak:
            b.set_color(GOLD_HI)

    # 軸・目盛り
    ax.set_xlim(-0.7, len(days) * 24 - 0.3)
    ax.set_ylim(0, peak + 2)
    ticks, labels = [], []
    for di in range(len(days)):
        for h in (0, 6, 12, 18):
            ticks.append(di * 24 + h)
            labels.append('%d' % h)
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, fontsize=8, color=MUTE)
    ax.set_ylabel('コミット数 / 時', fontsize=10, color=INK)
    ax.tick_params(axis='y', labelsize=9, colors=INK)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    for sp in ('left', 'bottom'):
        ax.spines[sp].set_color(MUTE)
    ax.grid(axis='y', color='#E2E8F0', lw=0.8, zorder=0)
    ax.set_axisbelow(True)

    # 日付・曜日・稼働帯ラベル（軸の下）
    for di, d in enumerate(days):
        day_times = sorted(t for t in times if t.date() == d)
        span = '%02d:%02d–%02d:%02d' % (day_times[0].hour, day_times[0].minute,
                                        day_times[-1].hour, day_times[-1].minute)
        n = sum(1 for t in times if t.date() == d)
        label = '%d/%d（%s）' % (d.month, d.day, JPW[d.weekday()])
        ax.text(di * 24 + 11.5, -0.16, label, transform=ax.get_xaxis_transform(),
                ha='center', va='top', fontsize=12, fontweight='bold', color=NAVY)
        ax.text(di * 24 + 11.5, -0.27, '%d commits / %s' % (n, span),
                transform=ax.get_xaxis_transform(),
                ha='center', va='top', fontsize=9, color=INK)

    # ピーク注記
    pk_x = heights.index(peak)
    ax.annotate('最多 %d commits' % peak, xy=(pk_x, peak),
                xytext=(pk_x + 1.5, peak + 0.3), fontsize=9, color=GOLD,
                fontweight='bold',
                arrowprops=dict(arrowstyle='-', color=GOLD, lw=1))

    title = '開発アクティビティ｜1時間ごとのコミット数（JST）'
    sub = '%d commits ／ %d日間（%s〜%s）／ 全コミットが DD に紐づく' % (
        total, len(days), days[0].strftime('%Y-%m-%d'), days[-1].strftime('%m-%d'))
    ax.set_title(title, fontsize=15, fontweight='bold', color=NAVY, loc='left', pad=18)
    ax.text(0.0, 1.045, sub, transform=ax.transAxes, fontsize=10, color=INK, ha='left')

    fig.subplots_adjust(left=0.05, right=0.99, top=0.87, bottom=0.24)
    fig.savefig(OUT, facecolor='white')
    print('Saved: %s  (%d commits, %d days, peak=%d)' % (OUT, total, len(days), peak))


if __name__ == '__main__':
    main()
