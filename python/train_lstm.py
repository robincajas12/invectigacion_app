import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
torch.set_num_threads(1)

SEQ_LEN = 5
HIDDEN_DIM = 48
NUM_LAYERS = 2
DROPOUT = 0.2
EPOCHS = 250
LR = 0.008
WEIGHT_DECAY = 1e-4

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")


class LSTMForecaster(nn.Module):
    def __init__(self, input_dim, hidden_dim=HIDDEN_DIM, output_dim=None, num_layers=NUM_LAYERS):
        super().__init__()
        if output_dim is None:
            output_dim = input_dim
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True, dropout=DROPOUT)
        self.linear = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.linear(out[:, -1, :])


def load_timeseries():
    path = os.path.join(DATA_DIR, "metagame_time_series.csv")
    df = pd.read_csv(path)
    archetypes = [c for c in df.columns if c != "ds"]
    print(f"Loaded {len(df)} windows, {len(archetypes)} archetypes")
    return df, archetypes


def train():
    df, archetypes = load_timeseries()
    n_features = len(archetypes)

    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(df[archetypes].values)

    X, y = [], []
    for i in range(len(scaled) - SEQ_LEN):
        X.append(scaled[i:i + SEQ_LEN])
        y.append(scaled[i + SEQ_LEN])
    X, y = np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

    split = int(len(X) * 0.8)
    X_train, y_train = X[:split], y[:split]

    X_t = torch.FloatTensor(X_train)
    y_t = torch.FloatTensor(y_train)

    model = LSTMForecaster(input_dim=n_features)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    criterion = nn.MSELoss()

    print("Training LSTM...")
    for epoch in range(EPOCHS):
        model.train()
        optimizer.zero_grad()
        out = model(X_t)
        loss = criterion(out, y_t)
        loss.backward()
        optimizer.step()
        if (epoch + 1) % 50 == 0:
            print(f"  Epoch {epoch+1}/{EPOCHS}  loss={loss.item():.6f}")

    return model, scaler, n_features


def export_onnx(model, scaler, n_features):
    os.makedirs(MODELS_DIR, exist_ok=True)
    out_path = os.path.join(MODELS_DIR, "lstm_meta.onnx")

    model.eval()
    dummy = torch.randn(1, SEQ_LEN, n_features)
    torch.onnx.export(
        model, dummy, out_path,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    print(f"LSTM exported -> {out_path}")

    import onnxruntime as ort
    session = ort.InferenceSession(out_path)
    test = torch.randn(1, SEQ_LEN, n_features).numpy()
    result = session.run(None, {"input": test})
    print(f"ONNX test output sum: {result[0].sum():.4f}")


if __name__ == "__main__":
    model, scaler, n_feat = train()
    export_onnx(model, scaler, n_feat)
