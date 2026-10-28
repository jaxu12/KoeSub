"""Compare sampled visible creator captions with pipeline output; not a full reference transcript."""
import argparse
import json
from pathlib import Path

from studio.core import atomic_text
from studio.pipeline_worker import read_json


# Independently read from the source frames, before inspecting the generated English.
# Some captions are sentence fragments. Never calculate whole-film WER/CER from these.
REFERENCE = [
    (3.5, 'みなさんこんにちは！熊谷望那です。', 'Powitanie; prowadząca Mona Kumagai.'),
    (7, 'イージージャパニーズは仙台からお送りします。', 'Easy Japanese jest nadawane z Sendai.'),
    (44, '周りが海なんで新鮮な魚いつでも', 'Otaczające morze; dostępność świeżych ryb — fragment zdania.'),
    (46.5, '手に入るっつうとこは一番いいところですね。', 'Łatwa dostępność świeżych ryb jest zaletą; dodatkowa próbka wybrana po wykryciu podejrzanego ASR.'),
    (63, 'んー、今ねなんか健康的に世界的に注目されてますもんね。', 'Zainteresowanie kuchnią japońską na świecie ze względu na zdrowie.'),
    (88, 'ロングの黒髪の女性がやっぱり一番', 'Kobiety z długimi czarnymi włosami — fragment zdania.'),
    (117, '例えば、食事しに行って、', 'Przykład wyjścia na posiłek — fragment zdania.'),
    (145, '例えば雪が降るにしても、', 'Przykład padającego śniegu — fragment zdania.'),
    (172, 'アニメですかね。', 'Chyba anime.'),
    (199, 'ちなみに今日僕たちは『プリキュア』を意識して。', 'Dzisiejszy wygląd inspirowany Pretty Cure.'),
    (220, 'ここあんま好きじゃないなあと思うニッポンの所ってある？', 'Pytanie, czego nie lubią w Japonii.'),
    (243, 'むかし我々若いとき『ヤバい』とかそういうのは', 'Dawne znaczenie słowa yabai — fragment zdania.'),
    (265, 'ごめんなさいね。何言ったらいいのか分からないんだけど。', 'Przeprosiny i brak pomysłu, co powiedzieć.'),
]


def compare(manifest):
    state = read_json(manifest)
    root = Path(manifest).parent
    tracks = {stage: read_json(root / stage / 'result.json')['track']['segments']
              for stage in ('asr-0', 'asr-1', 'asr-2', 'merge-1', 'merge-2', 'jp-review', 'jp-layout', 'choose-en', 'layout')
              if (root / stage / 'result.json').exists() and 'track' in read_json(root / stage / 'result.json')}
    rows = []
    for seconds, jp, meaning in REFERENCE:
        at = int(seconds * 1000)
        row = {'seconds': seconds, 'creator_jp_visible': jp, 'meaning_pl': meaning,
               'selection': 'targeted after inspecting ASR' if seconds == 46.5 else 'initial sample',
               'reference_frame': f'D:/models/test-media/easy-japanese-1/reference-frames/{"targeted-" if seconds == 46.5 else ""}{seconds:06.1f}.jpg'}
        for stage, segments in tracks.items():
            row[stage] = [dict(index=i + 1, **s) for i, s in enumerate(segments)
                          if s['start'] <= at < s['end']]
            if not row[stage]:
                nearest = min(enumerate(segments), key=lambda pair: min(abs(pair[1]['start'] - at), abs(pair[1]['end'] - at)))
                row[stage + '_nearest'] = dict(index=nearest[0] + 1, **nearest[1])
        rows.append(row)
    return {'manifest': str(manifest), 'scope': '12 initial samples and 1 targeted additional burned-in creator caption; fragments included. '
            'No complete independent SRT and no whole-film WER/CER. Caption timing may differ from speech timing.',
            'samples': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    atomic_text(args.out, json.dumps(compare(args.manifest), ensure_ascii=False, indent=2))
    print(args.out)
