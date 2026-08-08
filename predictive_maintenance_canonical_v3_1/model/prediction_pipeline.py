"""Independent compressor/CNC temporal models and explanation outputs.

Only canonical observation fields are used as features. Evaluation truth is
used solely to create the future-failure label. Asset relations and optional
experiment files are not loaded by this pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler


COMPRESSOR_SENSORS = [
    "voltage_raw",
    "rotation_raw",
    "pressure_raw",
    "vibration_raw",
    "relative_vibration_z",
]

CNC_SENSORS = [
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
    "tool_wear_min",
]

MODEL_VERSION = "independent-logreg-v3.1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_truth(path: Path) -> dict[str, np.ndarray]:
    frame = pd.read_csv(path, parse_dates=["failure_occurred_at"])
    result: dict[str, np.ndarray] = {}
    for asset_id, group in frame.groupby("asset_id"):
        # Pandas 3 may preserve microsecond-resolution dtypes. Convert explicitly
        # to nanoseconds so the 24-hour horizon uses the same integer unit.
        values = (
            group["failure_occurred_at"]
            .sort_values()
            .to_numpy(dtype="datetime64[ns]")
            .astype("int64")
        )
        result[str(asset_id)] = values
    return result


def future_label(
    timestamps: np.ndarray,
    event_times: np.ndarray,
    horizon_hours: int,
) -> np.ndarray:
    if len(event_times) == 0:
        return np.zeros(len(timestamps), dtype=np.int8)
    horizon_ns = int(timedelta(hours=horizon_hours).total_seconds() * 1_000_000_000)
    indices = np.searchsorted(event_times, timestamps, side="right")
    labels = np.zeros(len(timestamps), dtype=np.int8)
    valid = indices < len(event_times)
    labels[valid] = (
        event_times[indices[valid]] <= timestamps[valid] + horizon_ns
    ).astype(np.int8)
    return labels


def build_feature_table(
    observation_path: Path,
    truth_path: Path,
    sensors: list[str],
    horizon_hours: int,
) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.read_csv(observation_path, parse_dates=["observed_at"])
    truth = load_truth(truth_path)
    frames: list[pd.DataFrame] = []
    feature_columns: list[str] = []

    for asset_id, group in frame.groupby("asset_id", sort=True):
        group = group.sort_values("observed_at").reset_index(drop=True)
        raw_numeric = group[sensors].astype(float)
        baseline_end = group["observed_at"].iloc[0] + pd.Timedelta(days=7)
        baseline_mask = (group["observed_at"] < baseline_end) & (
            group["operating_state"] == "running"
        )
        baseline_mean = raw_numeric.loc[baseline_mask].mean()
        baseline_std = raw_numeric.loc[baseline_mask].std().replace(0.0, 1.0).fillna(1.0)
        # Normalize within each asset so the model learns temporal deviation,
        # not stable equipment-to-equipment baseline differences.
        numeric = (raw_numeric - baseline_mean) / baseline_std
        features = pd.DataFrame(index=group.index)
        for sensor in sensors:
            series = numeric[sensor]
            features[f"{sensor}_current"] = series
            features[f"{sensor}_6h_mean"] = series.rolling(36, min_periods=12).mean()
            features[f"{sensor}_6h_std"] = series.rolling(36, min_periods=12).std()
            features[f"{sensor}_6h_max_abs"] = series.abs().rolling(36, min_periods=12).max()
            features[f"{sensor}_6h_change"] = (series - series.shift(35)) / 6.0
            features[f"{sensor}_1h_change"] = series - series.shift(6)
            features[f"{sensor}_abs_current"] = series.abs()
            features[f"{sensor}_6h_abs_mean"] = series.abs().rolling(36, min_periods=12).mean()
        if not feature_columns:
            feature_columns = list(features.columns)

        # Keep one row per hour after a complete six-hour history.
        selected = np.arange(36, len(group), 6)
        sample = features.iloc[selected].copy()
        sample["asset_id"] = str(asset_id)
        sample["site_id"] = group.iloc[selected]["site_id"].to_numpy()
        sample["observed_at"] = group.iloc[selected]["observed_at"].to_numpy()
        sample["operating_state"] = group.iloc[selected]["operating_state"].to_numpy()
        timestamps = (
            sample["observed_at"].to_numpy(dtype="datetime64[ns]").astype("int64")
        )
        event_times = truth.get(str(asset_id), np.asarray([], dtype=np.int64))
        sample["label"] = future_label(timestamps, event_times, horizon_hours)
        # Truth is generated only inside the observation interval. Rows in the
        # final prediction horizon are right-censored because an event just past
        # the dataset boundary is unknown, not a confirmed negative. Maintenance
        # rows are also excluded from a pre-failure operating model.
        censor_cutoff = group["observed_at"].iloc[-1] - pd.Timedelta(hours=horizon_hours)
        sample = sample[
            (sample["observed_at"] <= censor_cutoff)
            & (sample["operating_state"] == "running")
        ]
        sample = sample.dropna(subset=feature_columns)
        frames.append(sample)

    if not frames:
        raise ValueError(f"no feature rows generated from {observation_path}")
    return pd.concat(frames, ignore_index=True), feature_columns


def fit_model(x: np.ndarray, y: np.ndarray) -> tuple[StandardScaler, LogisticRegression]:
    scaler = StandardScaler()
    transformed = scaler.fit_transform(x)
    model = LogisticRegression(
        max_iter=1500,
        class_weight="balanced",
        C=0.5,
        random_state=42,
    )
    model.fit(transformed, y)
    return scaler, model


def cross_validate(
    frame: pd.DataFrame,
    feature_columns: list[str],
) -> tuple[dict[str, object], np.ndarray, np.ndarray]:
    y = frame["label"].to_numpy(dtype=int)
    predictions = np.zeros(len(frame), dtype=float)
    contribution_matrix = np.zeros((len(frame), len(feature_columns)), dtype=float)
    folds: dict[str, object] = {}

    for site_id in sorted(frame["site_id"].unique()):
        test_mask = frame["site_id"].to_numpy() == site_id
        train_mask = ~test_mask
        train_y = y[train_mask]
        test_y = y[test_mask]
        if len(np.unique(train_y)) < 2:
            raise ValueError(f"training fold {site_id} has one class")
        scaler, model = fit_model(
            frame.loc[train_mask, feature_columns].to_numpy(dtype=float), train_y
        )
        test_x = scaler.transform(
            frame.loc[test_mask, feature_columns].to_numpy(dtype=float)
        )
        fold_prediction = model.predict_proba(test_x)[:, 1]
        predictions[test_mask] = fold_prediction
        contribution_matrix[test_mask] = test_x * model.coef_[0]
        fold_result: dict[str, object] = {
            "rows": int(test_mask.sum()),
            "positive_rows": int(test_y.sum()),
        }
        if 0 < test_y.sum() < len(test_y):
            fold_result["roc_auc"] = round(float(roc_auc_score(test_y, fold_prediction)), 6)
            fold_result["average_precision"] = round(
                float(average_precision_score(test_y, fold_prediction)), 6
            )
        else:
            fold_result["roc_auc"] = None
            fold_result["average_precision"] = None
        folds[str(site_id)] = fold_result

    top_count = max(1, int(len(predictions) * 0.05))
    top_indices = np.argpartition(predictions, -top_count)[-top_count:]
    metrics = {
        "rows": len(frame),
        "positive_rows": int(y.sum()),
        "prevalence": round(float(y.mean()), 6),
        "leave_one_site_out_roc_auc": round(float(roc_auc_score(y, predictions)), 6),
        "average_precision": round(float(average_precision_score(y, predictions)), 6),
        "top_5pct_precision": round(float(y[top_indices].mean()), 6),
        "top_5pct_recall": round(float(y[top_indices].sum() / max(1, y.sum())), 6),
        "folds": folds,
    }
    return metrics, predictions, contribution_matrix


def explain_latest(
    frame: pd.DataFrame,
    feature_columns: list[str],
    asset_type: str,
    horizon_hours: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
    x = frame[feature_columns].to_numpy(dtype=float)
    y = frame["label"].to_numpy(dtype=int)
    scaler, model = fit_model(x, y)
    latest = (
        frame.sort_values("observed_at")
        .groupby("asset_id", as_index=False)
        .tail(1)
        .sort_values("asset_id")
    )
    latest_x = latest[feature_columns].to_numpy(dtype=float)
    latest_scaled = scaler.transform(latest_x)
    probabilities = model.predict_proba(latest_scaled)[:, 1]

    explanation_method = "linear_logit_contribution"
    contribution_matrix = latest_scaled * model.coef_[0]
    try:
        import shap  # type: ignore

        explainer = shap.LinearExplainer(model, scaler.transform(x))
        contribution_matrix = np.asarray(explainer(latest_scaled).values)
        explanation_method = "shap_linear"
    except Exception:
        # The exact standardized linear-logit term remains a valid, transparent fallback.
        pass

    snapshots: list[dict[str, object]] = []
    factors: list[dict[str, object]] = []
    for row_index, (_index, row) in enumerate(latest.iterrows()):
        probability = float(probabilities[row_index])
        prediction_id = f"{row['asset_id']}#{pd.Timestamp(row['observed_at']).isoformat()}"
        status = (
            "critical"
            if probability >= 0.75
            else "warning"
            if probability >= 0.45
            else "attention"
            if probability >= 0.20
            else "normal"
        )
        snapshots.append(
            {
                "prediction_id": prediction_id,
                "asset_id": row["asset_id"],
                "asset_type": asset_type,
                "observed_at": pd.Timestamp(row["observed_at"]).isoformat(),
                "prediction_horizon_hours": horizon_hours,
                "failure_probability": round(probability, 6),
                "predicted_failure_type": (
                    "failure_risk" if probability >= 0.5 else "no_significant_risk"
                ),
                "confidence": round(abs(probability - 0.5) * 2.0, 6),
                "status": status,
                "model_version": MODEL_VERSION,
                "feature_scope": f"{asset_type}_canonical_only",
            }
        )

        contributions = contribution_matrix[row_index]
        ranked = np.argsort(-np.abs(contributions))[:3]
        for rank, feature_index in enumerate(ranked, start=1):
            feature_name = feature_columns[int(feature_index)]
            value = float(row[feature_name])
            contribution = float(contributions[int(feature_index)])
            factors.append(
                {
                    "prediction_id": prediction_id,
                    "rank": rank,
                    "feature": feature_name,
                    "feature_value": round(value, 6),
                    "signed_contribution": round(contribution, 6),
                    "absolute_contribution": round(abs(contribution), 6),
                    "direction": "risk_up" if contribution > 0 else "risk_down",
                    "explanation_method": explanation_method,
                    "source_type": "derived_model_output",
                }
            )
    return snapshots, factors, explanation_method


def build_prediction_timeline(
    frame: pd.DataFrame,
    feature_columns: list[str],
    asset_type: str,
    horizon_hours: int,
    probabilities: np.ndarray,
    contributions: np.ndarray,
) -> list[dict[str, object]]:
    """Create deterministic hourly replay rows from out-of-fold predictions.

    Every site's timeline is produced by a model trained on the other sites.
    The replay server therefore reads precomputed, non-in-sample site-holdout
    predictions and never trains a model while seeking or accelerating time.
    """

    rows: list[dict[str, object]] = []
    for row_index, (_index, row) in enumerate(frame.iterrows()):
        probability = float(probabilities[row_index])
        ranked = np.argsort(-np.abs(contributions[row_index]))[:3]
        top_factors = []
        for feature_index in ranked:
            contribution = float(contributions[row_index][int(feature_index)])
            top_factors.append(
                {
                    "feature": feature_columns[int(feature_index)],
                    "signed_contribution": round(contribution, 6),
                    "direction": "risk_up" if contribution > 0 else "risk_down",
                }
            )
        rows.append(
            {
                "prediction_id": (
                    f"{row['asset_id']}#{pd.Timestamp(row['observed_at']).isoformat()}"
                ),
                "asset_id": str(row["asset_id"]),
                "asset_type": asset_type,
                "observed_at": pd.Timestamp(row["observed_at"]).isoformat(),
                "prediction_horizon_hours": horizon_hours,
                "failure_probability": round(probability, 6),
                "status": (
                    "critical"
                    if probability >= 0.75
                    else "warning"
                    if probability >= 0.45
                    else "attention"
                    if probability >= 0.20
                    else "normal"
                ),
                "top_factors": top_factors,
                "model_version": MODEL_VERSION,
                "feature_scope": f"{asset_type}_canonical_only",
                "source_type": "derived_replay_prediction",
            }
        )
    return rows


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_result_artifacts(
    snapshots: list[dict[str, object]],
    factors: list[dict[str, object]],
    dataset_version: str,
) -> list[dict[str, object]]:
    factors_by_prediction: dict[str, list[dict[str, object]]] = defaultdict(list)
    for factor in factors:
        factors_by_prediction[str(factor["prediction_id"])].append(factor)

    action_by_status = {
        "critical": {
            "action": "immediate_inspection_and_stop_review",
            "priority": "urgent",
        },
        "warning": {
            "action": "inspect_within_current_shift",
            "priority": "high",
        },
        "attention": {
            "action": "schedule_targeted_diagnostic_check",
            "priority": "medium",
        },
        "normal": {
            "action": "continue_monitoring",
            "priority": "routine",
        },
    }
    artifacts: list[dict[str, object]] = []
    for snapshot in snapshots:
        prediction_id = str(snapshot["prediction_id"])
        status = str(snapshot["status"])
        artifacts.append(
            {
                "artifact_id": f"RESULT#{prediction_id}",
                "artifact_type": "predictive_maintenance_result",
                "schema_version": "result-artifact-v1.0",
                "asset_id": snapshot["asset_id"],
                "asset_type": snapshot["asset_type"],
                "observed_at": snapshot["observed_at"],
                "prediction_horizon_hours": snapshot["prediction_horizon_hours"],
                "prediction_task": "binary_failure_within_horizon",
                "failure_probability": snapshot["failure_probability"],
                "predicted_failure_type": snapshot["predicted_failure_type"],
                "status_grade": status,
                "confidence": snapshot["confidence"],
                "top_factors": [
                    {
                        "rank": factor["rank"],
                        "feature": factor["feature"],
                        "feature_value": factor["feature_value"],
                        "signed_contribution": factor["signed_contribution"],
                        "direction": factor["direction"],
                        "explanation_method": factor["explanation_method"],
                    }
                    for factor in sorted(
                        factors_by_prediction[prediction_id],
                        key=lambda item: int(item["rank"]),
                    )
                ],
                "recommended_action": action_by_status[status],
                "provenance": {
                    "dataset_version": dataset_version,
                    "model_version": MODEL_VERSION,
                    "prediction_id": prediction_id,
                    "source_type": "derived_result_artifact",
                    "canonical_source_mutated": False,
                },
            }
        )
    return artifacts


def run(root: Path, horizon_hours: int) -> dict[str, object]:
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    dataset_dir = root / "canonical" / "dataset"
    truth_dir = root / "canonical" / "evaluation_truth"
    output_dir = root / "canonical" / "model_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dataset_dir / "dataset_manifest.json"
    dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    specifications = [
        (
            "compressor",
            dataset_dir / "compressor_sensor_observation.csv",
            truth_dir / "compressor_failure_truth.csv",
            COMPRESSOR_SENSORS,
        ),
        (
            "cnc",
            dataset_dir / "cnc_sensor_observation.csv",
            truth_dir / "cnc_failure_truth.csv",
            CNC_SENSORS,
        ),
    ]

    all_snapshots: list[dict[str, object]] = []
    all_factors: list[dict[str, object]] = []
    all_timeline_rows: list[dict[str, object]] = []
    metrics: dict[str, object] = {}
    explanation_methods: dict[str, str] = {}

    for asset_type, observation_path, truth_path, sensors in specifications:
        frame, feature_columns = build_feature_table(
            observation_path, truth_path, sensors, horizon_hours
        )
        asset_metrics, oof_predictions, oof_contributions = cross_validate(
            frame, feature_columns
        )
        snapshots, factors, explanation_method = explain_latest(
            frame, feature_columns, asset_type, horizon_hours
        )
        timeline_rows = build_prediction_timeline(
            frame,
            feature_columns,
            asset_type,
            horizon_hours,
            oof_predictions,
            oof_contributions,
        )
        metrics[asset_type] = {
            **asset_metrics,
            "feature_count": len(feature_columns),
            "features": feature_columns,
        }
        explanation_methods[asset_type] = explanation_method
        all_snapshots.extend(snapshots)
        all_factors.extend(factors)
        all_timeline_rows.extend(timeline_rows)

    snapshot_path = output_dir / "prediction_snapshot.jsonl"
    factor_path = output_dir / "prediction_factor.jsonl"
    timeline_path = output_dir / "prediction_timeline.jsonl"
    result_artifact_path = output_dir / "result_artifact.jsonl"
    metrics_path = output_dir / "model_metrics.json"
    contract_path = output_dir / "model_contract.json"
    write_jsonl(snapshot_path, all_snapshots)
    write_jsonl(factor_path, all_factors)
    write_jsonl(timeline_path, all_timeline_rows)
    result_artifacts = build_result_artifacts(
        all_snapshots,
        all_factors,
        str(dataset_manifest["dataset_version"]),
    )
    write_jsonl(result_artifact_path, result_artifacts)
    sample_artifact_path = root / "result_artifact_sample.json"
    sample_artifact = max(
        result_artifacts,
        key=lambda item: float(item["failure_probability"]),
    )
    sample_artifact_path.write_text(
        json.dumps(sample_artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    contract = {
        "model_version": MODEL_VERSION,
        "dataset_version": dataset_manifest["dataset_version"],
        "dataset_manifest_sha256": sha256(manifest_path),
        "canonical_input_sha256": dataset_manifest["canonical_outputs"],
        "evaluation_truth_input_sha256": dataset_manifest["evaluation_truth_outputs"],
        "prediction_horizon_hours": horizon_hours,
        "compressor_model_uses": COMPRESSOR_SENSORS,
        "cnc_model_uses": CNC_SENSORS,
        "asset_relation_used_as_feature": False,
        "upstream_feature_used": False,
        "optional_experiment_used_for_training": False,
        "truth_usage": "label creation and evaluation only",
        "right_censoring_policy": "exclude final prediction horizon",
        "maintenance_rows_excluded": True,
        "explanation_methods": explanation_methods,
        "replay_timeline": {
            "cadence": "hourly after six-hour feature warmup",
            "semantics": "derived leave-one-site-out out-of-fold output for deterministic replay",
            "uses_canonical_features_only": True,
            "in_sample_for_site": False,
            "row_count": len(all_timeline_rows),
        },
        "result_artifact": {
            "schema_version": "result-artifact-v1.0",
            "row_count": len(result_artifacts),
            "prediction_task": "binary_failure_within_horizon",
            "predicted_failure_type_semantics": (
                "generic binary risk class; not a multiclass failure-mode classifier"
            ),
        },
        "outputs_are_not_source_data": True,
        "output_sha256": {
            snapshot_path.name: sha256(snapshot_path),
            factor_path.name: sha256(factor_path),
            timeline_path.name: sha256(timeline_path),
            result_artifact_path.name: sha256(result_artifact_path),
            metrics_path.name: sha256(metrics_path),
        },
    }
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "metrics": metrics,
        "snapshot_count": len(all_snapshots),
        "factor_count": len(all_factors),
        "timeline_count": len(all_timeline_rows),
        "result_artifact_count": len(result_artifacts),
        "contract": contract,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train independent source-only temporal models")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--horizon-hours", type=int, default=24)
    args = parser.parse_args()
    result = run(Path(args.root), args.horizon_hours)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
