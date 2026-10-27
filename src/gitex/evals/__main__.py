"""`uv run python -m gitex.evals` — değerlendirme setini çalıştırır ve skorlar."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from gitex.config import load_config
from gitex.errors import GitexError
from gitex.evals.runner import CaseResult, default_questions_path, load_cases, run_evals


def _mark(value: bool | None) -> str:
    return "-" if value is None else ("✓" if value else "✗")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gitex.evals", description=__doc__)
    parser.add_argument(
        "--questions", type=Path, help="Soru seti (varsayılan: evals/questions.toml)"
    )
    parser.add_argument("--mode", choices=["agent", "simple"], help="Config'teki modu ez")
    parser.add_argument("--provider", choices=["openai_compat", "anthropic"])
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument(
        "--case", action="append", default=[], help="Yalnızca bu id'ler (tekrarlanabilir)"
    )
    parser.add_argument("--json", action="store_true", help="Sonucu JSON olarak yaz")
    parser.add_argument("--output", type=Path, help="JSON raporu bu dosyaya da yaz")
    args = parser.parse_args(argv)

    console = Console(stderr=True)
    try:
        cfg = load_config(None)
        overrides = {
            k: v
            for k, v in (
                ("provider", args.provider),
                ("model", args.model),
                ("base_url", args.base_url),
            )
            if v
        }
        if overrides:
            cfg = cfg.model_copy(update={"llm": cfg.llm.model_copy(update=overrides)})
        cases = load_cases(args.questions or default_questions_path())
        if args.case:
            cases = [c for c in cases if c.id in set(args.case)]

        def on_case(r: CaseResult) -> None:
            status = "HATA" if r.error else f"isabet {r.recall:.0%}"
            console.print(f"[dim]{r.case.id}: {status}, {r.tool_calls} araç, {r.seconds:.1f} sn[/]")

        report = run_evals(cfg, cases, mode=args.mode, on_case=on_case)
    except GitexError as exc:
        console.print(f"[bold red]Hata:[/] {exc}")
        if exc.hint:
            console.print(f"[dim]İpucu: {exc.hint}[/]")
        return 1

    payload = report.to_dict()
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    out = Console()
    table = Table(title=f"gitex eval — {report.model} ({report.mode})")
    for col in ("id", "isabet", "uydurma", "metin", "bulamadım", "düzeltme", "araç"):
        table.add_column(col)
    for r in report.results:
        table.add_row(
            r.case.id,
            "HATA" if r.error else f"{r.recall:.0%}",
            str(len(r.unverified)),
            _mark(r.text_ok),
            _mark(r.not_found_ok),
            "✓" if r.corrected else "",
            str(r.tool_calls),
        )
    out.print(table)
    s = report.summary()
    out.print(
        f"Kaynak isabeti: [bold]{s['source_recall']:.0%}[/] · tam isabet: {s['full_hit_rate']:.0%} · "
        f"uydurma referans oranı: [bold]{s['fabricated_ref_rate']:.0%}[/] · "
        f"bulamadım doğruluğu: {s['not_found_accuracy'] if s['not_found_accuracy'] is not None else '-'} · "
        f"hata: {s['errors']} · token: {s['total_tokens']} · süre: {s['total_seconds']} sn"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
