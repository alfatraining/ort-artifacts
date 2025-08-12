Static builds of [onnxruntime](https://github.com/microsoft/onnxruntime) for various platforms.

ToDo:
- Debug builds.
- KleidiAI?
- Builds for Android.
- Builds for iOS.
- Custom CMake build of Emscripten.
- Add NPU-based execution providers (QNN?, Intel OpenVINO?, [AMD?](https://onnxruntime.ai/docs/execution-providers/Vitis-AI-ExecutionProvider.html), ...).
- Option to compile WebGPU ep with Vulkan backend under Windows?

Changes from [pykeio/ort-artifacts](https://github.com/pykeio/ort-artifacts) should be reviewed and merged into this fork.
Currently, the latest commit until reviewed was [2793c2e](https://github.com/pykeio/ort-artifacts/tree/2793c2e33712de2f5c19435af438c95ceada8085).
