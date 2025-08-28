# PowerShell build script for ONNX Runtime
# Use all arguments directly
$Arguments = $args

# Set strict mode for better error handling
Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

# Default values matching build.ts
$REFERENCE = "main"
$STATIC_BUILD = "OFF"
$USE_NINJA = "OFF"
$TARGET_ARCH = "x86_64"
$IPHONEOS = "OFF"
$IPHONESIMULATOR = "OFF"
$ANDROID = "OFF"
$ANDROID_API = "35"
$ANDROID_ABI = "arm64-v8a"
$WASM = "OFF"
$EMSDK_VERSION = "4.0.3"
$MSVC_STATIC_RUNTIME = "OFF"
$USE_DIRECTML = "OFF"
$USE_COREML = "OFF"
$USE_XNNPACK = "OFF"
$USE_WEBGPU = "OFF"
$USE_OPENVINO = "OFF"
$USE_NNAPI = "OFF"
$DRY_RUN = "OFF"

# Parse arguments
$i = 0
while ($i -lt $Arguments.Length) {
    switch ($Arguments[$i]) {
        { $_ -in @("-r", "--reference") } {
            $REFERENCE = $Arguments[$i + 1]
            $i += 2
        }
        { $_ -in @("-s", "--static") } {
            $STATIC_BUILD = "ON"
            $i++
        }
        { $_ -in @("-N", "--ninja") } {
            $USE_NINJA = "ON"
            $i++
        }
        { $_ -in @("-A", "--arch") } {
            $TARGET_ARCH = $Arguments[$i + 1]
            $i += 2
        }
        "--iphoneos" {
            $IPHONEOS = "ON"
            $i++
        }
        "--iphonesimulator" {
            $IPHONESIMULATOR = "ON"
            $i++
        }
        "--android" {
            $ANDROID = "ON"
            $i++
        }
        "--android_api" {
            $ANDROID_API = $Arguments[$i + 1]
            $i += 2
        }
        "--android_abi" {
            $ANDROID_ABI = $Arguments[$i + 1]
            $i += 2
        }
        { $_ -in @("-W", "--wasm") } {
            $WASM = "ON"
            $i++
        }
        "--emsdk" {
            $EMSDK_VERSION = $Arguments[$i + 1]
            $i += 2
        }
        "--mt" {
            $MSVC_STATIC_RUNTIME = "ON"
            $i++
        }
        "--directml" {
            $USE_DIRECTML = "ON"
            $i++
        }
        "--coreml" {
            $USE_COREML = "ON"
            $i++
        }
        "--xnnpack" {
            $USE_XNNPACK = "ON"
            $i++
        }
        "--webgpu" {
            $USE_WEBGPU = "ON"
            $i++
        }
        "--openvino" {
            $USE_OPENVINO = "ON"
            $i++
        }
        "--nnapi" {
            $USE_NNAPI = "ON"
            $i++
        }
        "--dry-run" {
            $DRY_RUN = "ON"
            $i++
        }
        { $_ -in @("-h", "--help") } {
            Write-Host "Usage: .\build.ps1 [options]"
            Write-Host ""
            Write-Host "Options:"
            Write-Host "  -r, --reference <string>     Exact branch or tag"
            Write-Host "  -s, --static                 Build static library"
            Write-Host "  -N, --ninja                  Build with Ninja"
            Write-Host "  -A, --arch <arch>            Configure target architecture (x86_64, aarch64)"
            Write-Host "      --iphoneos               Target iOS / iPadOS"
            Write-Host "      --iphonesimulator        Target iOS / iPadOS simulator"
            Write-Host "      --android                Target Android"
            Write-Host "      --android_api <number>   Android API (default: 35)"
            Write-Host "      --android_abi <abi>      Android ABI (default: arm64-v8a)"
            Write-Host "  -W, --wasm                   Compile for WebAssembly"
            Write-Host "      --emsdk <version>        Emsdk version for WebAssembly (default: 4.0.3)"
            Write-Host "      --mt                     Link with static MSVC runtime"
            Write-Host "      --directml               Enable DirectML EP"
            Write-Host "      --coreml                 Enable CoreML EP"
            Write-Host "      --xnnpack                Enable XNNPACK EP"
            Write-Host "      --webgpu                 Enable WebGPU EP"
            Write-Host "      --openvino               Enable OpenVINO EP"
            Write-Host "      --nnapi                  Enable NNAPI EP"
            Write-Host "      --dry-run                Print CMake command without executing"
            Write-Host "  -h, --help                   Show this help message"
            exit 0
        }
        default {
            Write-Error "Unknown option: $($Arguments[$i])"
            Write-Host "Use -h or --help for usage information" -ForegroundColor Red
            exit 1
        }
    }
}

# Prepare generator argument
$GeneratorArgs = @()
if ($USE_NINJA -eq "ON") {
    $GeneratorArgs += "-G", "Ninja"
}

Write-Host "Configuring ONNX Runtime build with CMake..." -ForegroundColor Green

# Prepare CMake arguments
$CMakeArgs = @(
    "-S", "."
    "-B", "build"
    "-DREFERENCE=$REFERENCE"
    "-DSTATIC_BUILD=$STATIC_BUILD"
    "-DUSE_NINJA=$USE_NINJA"
    "-DTARGET_ARCH=$TARGET_ARCH"
    "-DIPHONEOS=$IPHONEOS"
    "-DIPHONESIMULATOR=$IPHONESIMULATOR"
    "-DANDROID=$ANDROID"
    "-DANDROID_API=$ANDROID_API"
    "-DANDROID_ABI=$ANDROID_ABI"
    "-DWASM=$WASM"
    "-DEMSDK_VERSION=$EMSDK_VERSION"
    "-DMSVC_STATIC_RUNTIME=$MSVC_STATIC_RUNTIME"
    "-DUSE_DIRECTML=$USE_DIRECTML"
    "-DUSE_COREML=$USE_COREML"
    "-DUSE_XNNPACK=$USE_XNNPACK"
    "-DUSE_WEBGPU=$USE_WEBGPU"
    "-DUSE_OPENVINO=$USE_OPENVINO"
    "-DUSE_NNAPI=$USE_NNAPI"
)

# Add generator arguments if specified
$CMakeArgs += $GeneratorArgs

if ($DRY_RUN -eq "ON") {
    Write-Host "DRY RUN MODE - Commands that would be executed:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "cmake $($CMakeArgs -join ' ')" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "cmake --build build --config Release --parallel" -ForegroundColor Cyan
    exit 0
}

try {
    # Execute CMake configuration
    Write-Host "Running: cmake $($CMakeArgs -join ' ')" -ForegroundColor Cyan
    & cmake @CMakeArgs
    
    if ($LASTEXITCODE -ne 0) {
        throw "CMake configuration failed with exit code $LASTEXITCODE"
    }
    
    Write-Host "Building ONNX Runtime..." -ForegroundColor Green
    
    # Build the project
    & cmake --build build --config Release --parallel
    
    if ($LASTEXITCODE -ne 0) {
        throw "CMake build failed with exit code $LASTEXITCODE"
    }
    
    Write-Host "Build completed successfully!" -ForegroundColor Green
}
catch {
    Write-Error "Build failed: $_"
    exit 1
}