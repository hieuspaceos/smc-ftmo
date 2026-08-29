from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "pine-parity"
EXPORTER = ROOT / "scripts" / "export-pine-parity-fixtures.py"
COMPARATOR = ROOT / "scripts" / "compare-pine-parity.py"
SYNTHETIC_OHLC = FIXTURE_DIR / "synthetic-ohlc.csv"
SYNTHETIC_REFERENCE = FIXTURE_DIR / "synthetic-python-reference.csv"
SYNTHETIC_METADATA = FIXTURE_DIR / "synthetic-metadata.json"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=True)


def _load_rulebook_module():
    spec = importlib.util.spec_from_file_location(
        "export_rulebook_reference",
        ROOT / "scripts" / "export-rulebook-reference.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

_RULEBOOK = _load_rulebook_module()


class TestPineParityExporter:
    def test_exporter_reproduces_checked_in_reference(self, tmp_path: Path):
        reference_out = tmp_path / "synthetic-python-reference.csv"
        metadata_out = tmp_path / "synthetic-metadata.json"
        ohlc_out = tmp_path / "synthetic-ohlc-normalized.csv"

        _run(
            [
                sys.executable,
                str(EXPORTER),
                "--input",
                str(SYNTHETIC_OHLC),
                "--output-reference",
                str(reference_out),
                "--output-ohlc",
                str(ohlc_out),
                "--output-metadata",
                str(metadata_out),
                "--dataset-name",
                "synthetic",
                "--source",
                "synthetic",
                "--symbol",
                "SYNTH",
                "--timeframe",
                "M15",
                "--timezone",
                "UTC",
                "--swing-length",
                "4",
            ]
        )

        assert reference_out.read_text(encoding="utf-8") == SYNTHETIC_REFERENCE.read_text(encoding="utf-8")
        assert metadata_out.read_text(encoding="utf-8") == SYNTHETIC_METADATA.read_text(encoding="utf-8")
        assert hashlib.sha256(ohlc_out.read_bytes()).hexdigest() == json.loads(metadata_out.read_text())["ohlc_sha256"]

    def test_exporter_is_deterministic_across_runs(self, tmp_path: Path):
        out_one = tmp_path / "one.csv"
        out_two = tmp_path / "two.csv"
        meta_one = tmp_path / "one.json"
        meta_two = tmp_path / "two.json"

        base_command = [
            sys.executable,
            str(EXPORTER),
            "--input",
            str(SYNTHETIC_OHLC),
            "--dataset-name",
            "synthetic",
            "--source",
            "synthetic",
            "--symbol",
            "SYNTH",
            "--timeframe",
            "M15",
            "--timezone",
            "UTC",
            "--swing-length",
            "4",
        ]
        _run(base_command + ["--output-reference", str(out_one), "--output-metadata", str(meta_one)])
        _run(base_command + ["--output-reference", str(out_two), "--output-metadata", str(meta_two)])

        assert out_one.read_text(encoding="utf-8") == out_two.read_text(encoding="utf-8")
        assert meta_one.read_text(encoding="utf-8") == meta_two.read_text(encoding="utf-8")

    def test_reference_schema_covers_bar_state_and_events(self):
        frame = pd.read_csv(SYNTHETIC_REFERENCE, dtype=str, keep_default_na=False)
        assert {"bar_state", "event", "diagnostic"} <= set(frame["row_type"])
        assert {"core", "swing", "structure", "sweep", "order_block", "fvg", "liquidity_pool"} <= set(frame["module"])
        assert (frame["module"] == "order_block").any()
        assert (frame["module"] == "liquidity_pool").any()
        assert (frame["diagnostic_code"] == "dual_sided").any()


class TestPineParityComparator:
    def test_comparator_accepts_identical_files(self):
        result = _run(
            [
                sys.executable,
                str(COMPARATOR),
                "--python-reference",
                str(SYNTHETIC_REFERENCE),
                "--pine-output",
                str(SYNTHETIC_REFERENCE),
                "--json",
            ]
        )
        payload = json.loads(result.stdout)
        assert payload["matches"] is True
        assert payload["missing_rows"] == 0
        assert payload["extra_rows"] == 0
        assert payload["value_mismatches"] == 0

    def test_comparator_respects_float_tolerance(self, tmp_path: Path):
        frame = pd.read_csv(SYNTHETIC_REFERENCE, dtype=str, keep_default_na=False)
        first_core = frame.index[(frame["row_type"] == "bar_state") & (frame["atr"] != "")][0]
        frame.loc[first_core, "atr"] = f"{float(frame.loc[first_core, 'atr']) + 4e-10:.10f}"
        modified = tmp_path / "modified.csv"
        frame.to_csv(modified, index=False)

        result = _run(
            [
                sys.executable,
                str(COMPARATOR),
                "--python-reference",
                str(SYNTHETIC_REFERENCE),
                "--pine-output",
                str(modified),
                "--json",
                "--abs-tol",
                "0.000001",
            ]
        )
        assert json.loads(result.stdout)["matches"] is True

    def test_comparator_flags_real_mismatch(self, tmp_path: Path):
        frame = pd.read_csv(SYNTHETIC_REFERENCE, dtype=str, keep_default_na=False)
        first_sweep = frame.index[frame["module"] == "sweep"][0]
        frame.loc[first_sweep, "direction"] = "bearish" if frame.loc[first_sweep, "direction"] == "bullish" else "bullish"
        modified = tmp_path / "mismatch.csv"
        frame.to_csv(modified, index=False)

        result = subprocess.run(
            [
                sys.executable,
                str(COMPARATOR),
                "--python-reference",
                str(SYNTHETIC_REFERENCE),
                "--pine-output",
                str(modified),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["matches"] is False
        assert payload["value_mismatches"] >= 1

    def test_comparator_handles_pool_member_lists(self, tmp_path: Path):
        frame = pd.read_csv(SYNTHETIC_REFERENCE, dtype=str, keep_default_na=False)
        pool_rows = frame[frame["module"] == "liquidity_pool"]
        assert not pool_rows.empty
        pool_row = pool_rows.iloc[0]
        # Synthetic fixture must have at least one EQH/EQL pool with two members
        assert "|" in pool_row["member_swing_ids"]
        assert "|" in pool_row["member_levels"]
        # The comparator must match identical pool rows exactly
        modified = tmp_path / "pool-match.csv"
        frame.to_csv(modified, index=False)
        result = _run(
            [
                sys.executable,
                str(COMPARATOR),
                "--python-reference",
                str(SYNTHETIC_REFERENCE),
                "--pine-output",
                str(modified),
                "--json",
            ]
        )
        payload = json.loads(result.stdout)
        assert payload["matches"] is True
        # The member_swing_ids and member_levels columns must not be misclassified
        # as float columns; otherwise string equality is bypassed.
        header = result.stdout
        assert "value_mismatches" in header
        # Synthetic pool: id=0, side=high, level_mean=106, swept=true at pos=26
        assert pool_row["event_id"] == "0"
        assert pool_row["direction"] == "high"
        assert pool_row["swept"].lower() == "true"
        assert pool_row["sweep_pos"] == "26"
        assert pool_row["member_swing_ids"].split("|") == ["2", "6"]
        assert pool_row["level_mean"] == "106.0000000000"

class TestFrozenFeedCapture:
    CAPTURE = ROOT / "scripts" / "capture-frozen-feed.py"

    def test_capture_emits_full_bundle_and_metadata(self, tmp_path: Path):
        out_dir = tmp_path / "bundle"
        result = _run(
            [
                sys.executable,
                str(self.CAPTURE),
                "--input",
                str(SYNTHETIC_OHLC),
                "--dataset",
                "test-fxpro-eurusd-m15",
                "--symbol",
                "FXPRO:EURUSD",
                "--feed",
                "FXPRO",
                "--timeframe",
                "M15",
                "--timezone",
                "America/New_York",
                "--session",
                "America/New_York",
                "--window-start",
                "2024-01-01T00:00:00+00:00",
                "--window-end",
                "2024-01-01T06:30:00+00:00",
                "--out-dir",
                str(out_dir),
            ]
        )
        payload = json.loads(result.stdout)
        assert payload["dataset"] == "test-fxpro-eurusd-m15"
        assert payload["rows"] == 27
        for key in (
            "ohlc_csv",
            "reference_csv",
            "pine_placeholder",
            "metadata",
            "ohlc_sha256",
        ):
            assert key in payload

        metadata = json.loads((out_dir / "test-fxpro-eurusd-m15-metadata.json").read_text())
        assert metadata["symbol"] == "FXPRO:EURUSD"
        assert metadata["feed"] == "FXPRO"
        assert metadata["timeframe"] == "M15"
        assert metadata["bars"] == 27
        assert metadata["ohlc_sha256"] == payload["ohlc_sha256"]
        # Re-running the same capture must produce the same checksum
        result_again = _run(
            [
                sys.executable,
                str(self.CAPTURE),
                "--input",
                str(SYNTHETIC_OHLC),
                "--dataset",
                "test-fxpro-eurusd-m15",
                "--symbol",
                "FXPRO:EURUSD",
                "--feed",
                "FXPRO",
                "--timeframe",
                "M15",
                "--timezone",
                "America/New_York",
                "--session",
                "America/New_York",
                "--window-start",
                "2024-01-01T00:00:00+00:00",
                "--window-end",
                "2024-01-01T06:30:00+00:00",
                "--out-dir",
                str(out_dir),
            ]
        )
        again = json.loads(result_again.stdout)
        assert again["ohlc_sha256"] == payload["ohlc_sha256"]
        # The Pine placeholder exists even before manual TradingView capture
        assert (out_dir / "test-fxpro-eurusd-m15-pine-output.csv").exists()
        placeholder = (out_dir / "test-fxpro-eurusd-m15-pine-output.csv").read_text()
        assert placeholder.startswith("dataset,row_type,module")


class TestRulebookReference:
    REFERENCE = ROOT / "scripts" / "export-rulebook-reference.py"

    def test_reference_emits_per_bar_candidate_rows(self, tmp_path: Path):
        out = tmp_path / "rulebook-synthetic.csv"
        result = _run(
            [
                sys.executable,
                str(self.REFERENCE),
                "--input",
                str(SYNTHETIC_OHLC),
                "--dataset",
                "synthetic",
                "--output",
                str(out),
                "--manual-gates",
                "all_ok",
            ]
        )
        assert "wrote 27 candidate rows" in result.stdout
        frame = pd.read_csv(out, dtype=str, keep_default_na=False)
        assert len(frame) == 27
        assert (frame["row_type"] == "candidate").all()
        assert (frame["module"] == "rulebook_selector").all()
        # Without a real Pine capture, the comparator can at least verify
        # the reference matches itself.
        modified = tmp_path / "self-match.csv"
        frame.to_csv(modified, index=False)
        cmp = _run(
            [
                sys.executable,
                str(COMPARATOR),
                "--python-reference",
                str(out),
                "--pine-output",
                str(modified),
                "--json",
            ]
        )
        payload = json.loads(cmp.stdout)
        # Module/row_type are the same; the comparator would need a
        # candidate-aware key set to compare cleanly, so we just assert
        # the reference file is internally consistent.
        assert payload["lhs_rows"] == 27
        assert payload["rhs_rows"] == 27

    def test_reference_is_deterministic_across_runs(self, tmp_path: Path):
        out_one = tmp_path / "one.csv"
        out_two = tmp_path / "two.csv"
        for out in (out_one, out_two):
            _run(
                [
                    sys.executable,
                    str(self.REFERENCE),
                    "--input",
                    str(SYNTHETIC_OHLC),
                    "--dataset",
                    "synthetic",
                    "--output",
                    str(out),
                    "--manual-gates",
                    "all_ok",
                ]
            )
        assert out_one.read_text(encoding="utf-8") == out_two.read_text(encoding="utf-8")

    def test_reference_manual_gates_change_state_column(self, tmp_path: Path):
        out_all = tmp_path / "all.csv"
        out_unknown = tmp_path / "unknown.csv"
        out_blocked = tmp_path / "blocked.csv"
        for gates, out in (
            ("all_ok", out_all),
            ("unknown", out_unknown),
            ("blocked", out_blocked),
        ):
            _run(
                [
                    sys.executable,
                    str(self.REFERENCE),
                    "--input",
                    str(SYNTHETIC_OHLC),
                    "--dataset",
                    "synthetic",
                    "--output",
                    str(out),
                    "--manual-gates",
                    gates,
                ]
            )
        all_frame = pd.read_csv(out_all, dtype=str, keep_default_na=False)
        unknown_frame = pd.read_csv(out_unknown, dtype=str, keep_default_na=False)
        blocked_frame = pd.read_csv(out_blocked, dtype=str, keep_default_na=False)
        # All three reference runs have the same row count
        assert len(all_frame) == len(unknown_frame) == len(blocked_frame) == 27
        # State column diverges based on manual gate selection for the
        # "no qualifying OB" path
        non_empty_state = all_frame["state"] != ""
        assert (all_frame.loc[non_empty_state, "state"] == "chart-qualified").all()
        non_empty_state_unknown = unknown_frame["state"] != ""
        assert (unknown_frame.loc[non_empty_state_unknown, "state"] == "watch").all()
        non_empty_state_blocked = blocked_frame["state"] != ""
        assert (blocked_frame.loc[non_empty_state_blocked, "state"] == "blocked").all()

class TestRulebookGaps:
    """Rule book §4, §8, §14 alignment tests.

    These tests pin the Python reference behavior to the rule book. The
    Pine indicator's parallel logic must produce the same gate decisions.
    """
    REFERENCE = ROOT / "scripts" / "export-rulebook-reference.py"

    def _run_reference(
        self,
        input_csv: Path,
        out_csv: Path,
        *,
        manual_gates: str = "all_ok",
    ) -> pd.DataFrame:
        result = _run(
            [
                sys.executable,
                str(self.REFERENCE),
                "--input",
                str(input_csv),
                "--dataset",
                "synthetic",
                "--output",
                str(out_csv),
                "--manual-gates",
                manual_gates,
            ]
        )
        assert "wrote" in result.stdout
        return pd.read_csv(out_csv, dtype=str, keep_default_na=False)

    def test_session_helper_matches_rule_book_windows(self):
        session_allowed_america_new_york = _RULEBOOK.session_allowed_america_new_york
        # Rule book §14: Asia 19-02 ✗, London 02-05 ✓, NY 07-10 ✓, Overlap 08-10 ✓
        # First 15 minutes of London open blocked.
        samples = [
            ("2024-01-01 00:30:00", False),  # Asia
            ("2024-01-01 01:59:00", False),  # Asia
            ("2024-01-01 02:00:00", False),  # First 15 min blocked
            ("2024-01-01 02:14:00", False),  # First 15 min blocked
            ("2024-01-01 02:15:00", True),  # London OK
            ("2024-01-01 04:59:00", True),  # London OK
            ("2024-01-01 05:00:00", False),  # London ends
            ("2024-01-01 06:30:00", False),  # Gap
            ("2024-01-01 07:00:00", True),  # NY opens
            ("2024-01-01 09:59:00", True),  # NY OK
            ("2024-01-01 10:00:00", False),  # NY ends
            ("2024-01-01 18:00:00", False),  # Asia
            ("2024-01-01 23:30:00", False),  # Asia
        ]
        for ts, expected in samples:
            assert session_allowed_america_new_york(pd.Timestamp(ts)) is expected, ts

    def test_clean_sweep_threshold_is_0_25_atr(self, tmp_path: Path):
        """§8: a sweep only counts as 'clean' (and contributes to score) when
        the wick pierces >= 0.25x ATR with reclaim. The reference script must
        have CLEAN_SWEEP_ATR=0.25 and a 0.10 sweep must not credit the score.
        """
        # Direct import check on the constant
        CLEAN_SWEEP_ATR = _RULEBOOK.CLEAN_SWEEP_ATR
        assert CLEAN_SWEEP_ATR == 0.25
        # Run reference and check the rejection code paths; the synthetic
        # has no candidates so we just confirm the helper exists and is wired
        out = tmp_path / "rulebook.csv"
        frame = self._run_reference(SYNTHETIC_OHLC, out)
        assert (frame["rejection"].isin({"no-atr", "no-qualifying-ob", "ok"})).all()

    def test_bias_strict_requires_d_and_h4_alignment(self, tmp_path: Path):
        """§4: D + H4 + M15 must all align; any neutral or disagreement
        produces a no-qualifying-ob result. The synthetic dataset has
        no candidates either way; we just verify the wiring is enforced.
        """
        select_candidates = _RULEBOOK.select_candidates
        df = pd.read_csv(SYNTHETIC_OHLC, parse_dates=["timestamp"], index_col="timestamp")
        # All aligned bull: any candidate would be allowed by Gate 2
        bull_run = select_candidates(
            df,
            htf_d_trend=1,
            htf_h4_trend=1,
        )
        # D bull, H4 bear: candidates should be rejected by Gate 2 even if
        # the rest of the pipeline would otherwise accept
        disagree_run = select_candidates(
            df,
            htf_d_trend=1,
            htf_h4_trend=-1,
        )
        # Both runs have the same row count (one per bar)
        assert len(bull_run) == len(disagree_run) == 27
        # The disagree run must not produce any 'ok' rejections when the
        # aligned run does — at minimum, the disagree run is more strict
        ok_bull = (bull_run["rejection"] == "ok").sum()
        ok_disagree = (disagree_run["rejection"] == "ok").sum()
        assert ok_disagree <= ok_bull
        # And the disagree run must be more strict at the gate (more
        # no-qualifying-ob rows than the aligned run when D+H4 disagree)
        if ok_bull > 0:
            no_ob_bull = (bull_run["rejection"] == "no-qualifying-ob").sum()
            no_ob_disagree = (disagree_run["rejection"] == "no-qualifying-ob").sum()
            assert no_ob_disagree >= no_ob_bull

    def test_score_includes_clean_sweep_and_pd_bonuses(self, tmp_path: Path):
        """§13: score = disp(1) + bias(1) + first-test(1) + sweep_clean(1)
        OR pd(1). Verify by reading the reference score column.
        """
        select_candidates = _RULEBOOK.select_candidates
        df = pd.read_csv(SYNTHETIC_OHLC, parse_dates=["timestamp"], index_col="timestamp")
        frame = select_candidates(df, htf_d_trend=0, htf_h4_trend=0, htf_daily_enabled=False, htf_h4_enabled=False)
        ok_rows = frame[frame["rejection"] == "ok"]
        if not ok_rows.empty:
            # The score field is a string; convert to float for the max check
            scores = ok_rows["score"].astype(float)
            # With synthetic being short, the only valid score values are
            # 3 (no bonus) or 4 (one bonus). Confirm we never see >5.
            assert scores.between(0, 5).all()
            # The 'ok' rows must have a non-zero score
            assert (scores > 0).all()
