"""Check installed libraries and exercise CUDA training and detection operators."""

import importlib
import sys

import torch
import torchvision


def main():
    print(f"Python: {sys.executable}")
    for name in (
        "cv2", "numpy", "PIL", "scipy", "pandas", "sklearn", "matplotlib",
        "seaborn", "ultralytics", "jupyterlab", "ipykernel", "ipywidgets",
        "tensorboard", "onnx", "onnxruntime", "timm", "transformers",
        "accelerate", "safetensors", "dotenv", "fastapi", "uvicorn", "pytest",
    ):
        importlib.import_module(name)
        print(f"Import OK: {name}")
    print(f"PyTorch: {torch.__version__}; torchvision: {torchvision.__version__}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable: select the AI environment with CUDA PyTorch.")
    print(f"GPU: {torch.cuda.get_device_name(0)}; CUDA runtime: {torch.version.cuda}")
    model = torch.nn.Conv2d(3, 8, 3).cuda()
    optimizer = torch.optim.Adam(model.parameters())
    loss = model(torch.randn(2, 3, 64, 64, device="cuda")).square().mean()
    loss.backward()
    optimizer.step()
    boxes = torch.tensor([[0., 0., 10., 10.], [1., 1., 9., 9.]], device="cuda")
    scores = torch.tensor([0.9, 0.8], device="cuda")
    kept = torchvision.ops.nms(boxes, scores, 0.5)
    assert kept.tolist() == [0], kept
    torch.cuda.synchronize()
    print("PASS: CUDA training step and torchvision GPU NMS")


if __name__ == "__main__":
    main()
