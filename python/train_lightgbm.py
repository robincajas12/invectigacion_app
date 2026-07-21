import os
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, mean_squared_error, mean_absolute_error

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

FEATURES = ["trophyDiff", "cardLevelDiff", "elixirCostDiff"]
N_FEATURES = len(FEATURES)


def load_cards():
    path = os.path.join(DATA_DIR, "CardMasterListSeason18_12082020.csv")
    return pd.read_csv(path)


def generate_battles(n=50000, seed=42):
    rng = np.random.default_rng(seed)
    records = []
    for _ in range(n):
        trophy_diff = float(rng.normal(0, 150))
        card_level_diff = float(rng.integers(-3, 4))
        elixir_diff = round(float(rng.normal(0, 0.8)), 2)
        skill_advantage = (abs(trophy_diff) * 0.001 + abs(card_level_diff) * 0.05)
        winner_won = 1 if rng.random() < 0.5 + skill_advantage * 0.3 else 0
        records.append({
            "trophyDiff": trophy_diff,
            "cardLevelDiff": card_level_diff,
            "elixirCostDiff": elixir_diff,
            "winnerWon": winner_won,
        })
    return pd.DataFrame(records)


def train():
    df = generate_battles()
    print(f"Generated {len(df)} synthetic battles")

    X = df[FEATURES].values.astype(np.float32)
    y = df["winnerWon"].values.astype(np.float32)

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    params = {
        "objective": "regression",
        "metric": "mse",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "max_depth": 3,
        "learning_rate": 0.05,
        "n_estimators": 1000,
        "verbose": -1,
        "seed": 42,
    }

    callbacks = [lgb.log_evaluation(period=100), lgb.early_stopping(stopping_rounds=50)]
    model = lgb.train(params, train_data, valid_sets=[val_data], callbacks=callbacks)

    y_pred = model.predict(X_val)
    y_pred_class = (y_pred > 0.5).astype(int)
    print(f"Accuracy: {accuracy_score(y_val, y_pred_class):.4f}")
    print(f"MSE: {mean_squared_error(y_val, y_pred):.6f}")
    print(f"MAE: {mean_absolute_error(y_val, y_pred):.6f}")

    return model


def export_onnx(model):
    from onnxmltools import convert_lightgbm
    from onnxmltools.convert.common.data_types import FloatTensorType
    from onnx import save as onnx_save

    os.makedirs(MODELS_DIR, exist_ok=True)
    out_path = os.path.join(MODELS_DIR, "lightgbm_regressor.onnx")

    initial_type = [("input", FloatTensorType([None, N_FEATURES]))]
    onnx_model = convert_lightgbm(model, initial_types=initial_type, target_opset=12)
    onnx_save(onnx_model, out_path)
    print(f"LightGBM regressor exported -> {out_path}")

    import onnxruntime as ort
    session = ort.InferenceSession(out_path)
    print(f"Outputs: {[o.name for o in session.get_outputs()]}")
    dummy = np.random.randn(1, N_FEATURES).astype(np.float32)
    result = session.run(None, {"input": dummy})
    print(f"ONNX output count: {len(result)}")
    for i, r in enumerate(result):
        print(f"  output[{i}]: shape={r.shape}, value={r}")


if __name__ == "__main__":
    model = train()
    export_onnx(model)
