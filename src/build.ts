import { exists } from 'https://deno.land/std@0.224.0/fs/mod.ts';
import { join } from 'https://deno.land/std@0.224.0/path/mod.ts';

import { arch as getArch, cpus, platform as getPlatform } from 'node:os';

import { Command, EnumType } from '@cliffy/command';
import $ from '@david/dax';

const arch: 'x64' | 'arm64' = getArch();
const platform: 'win32' | 'darwin' | 'linux' = getPlatform();

const TARGET_ARCHITECTURE_TYPE = new EnumType(['x86_64', 'aarch64']);

const MACOS_DEPLOYMENT_TARGET = 12.0; // Should be 13.3 according to https://github.com/microsoft/onnxruntime/releases/tag/v1.21.0. But due to internal constraints, we must target 12.
const IPHONE_DEPLOYMENT_TARGET = 16.0;

await new Command()
	.name('ort-artifact')
	.version('0.1.0')
	.type('target-arch', TARGET_ARCHITECTURE_TYPE)
	.option('-r, --reference <string>', 'Exact branch or tag')
	.option('-s, --static', 'Build static library')
	.option('--mt', 'Link with static MSVC runtime')
	.option('--directml', 'Enable DirectML EP')
	.option('--coreml', 'Enable CoreML EP')
	.option('--xnnpack', 'Enable XNNPACK EP')
	.option('--webgpu', 'Enable WebGPU EP')
	.option('--openvino', 'Enable OpenVINO EP')
	.option('-N, --ninja', 'build with ninja')
	.option('-A, --arch <arch:target-arch>', 'Configure target architecture for cross-compile', { default: 'x86_64' })
	.option('--iphoneos', 'Target iOS / iPadOS')
	.option('--iphonesimulator', 'Target iOS / iPadOS simulator')
	.option('--android', 'Target Android')
	.option('-W, --wasm', 'Compile for WebAssembly (with patches)')
	.option('--emsdk <version:string>', 'Emsdk version to use for WebAssembly build', { default: '4.0.3' })
	.action(async (options, ..._) => {
		const root = Deno.cwd();

		const onnxruntimeRoot = join(root, 'onnxruntime');
		if (!await exists(onnxruntimeRoot)) {
			await $`git clone https://github.com/microsoft/onnxruntime --recursive --single-branch --depth 1 --branch ${options.reference}`;
		}

		$.cd(onnxruntimeRoot);

		await $`git reset --hard HEAD`;
		await $`git clean -fd`;

		console.log("Applying patches...");
		const patchDir = join(root, 'src', 'patches', 'all');
		for await (const patchFile of Deno.readDir(patchDir)) {
			if (!patchFile.isFile) {
				continue;
			}
			console.log(`Applying ${patchFile.name}...`);
			await $`git apply ${join(patchDir, patchFile.name)} --ignore-whitespace --recount --verbose`;
			console.log(`Applied ${patchFile.name}!`);
		}
		console.log("All patches applied!");

		if (options.wasm) {
			// there's no WAY im gonna try to wrestle with CMake on this one
			await $`bash ./build.sh --config Release --build_wasm_static_lib --enable_wasm_simd --enable_wasm_threads --skip_tests --disable_wasm_exception_catching --disable_rtti --parallel ${options.webgpu ? "--use_webgpu" : ''} --emsdk_version ${options.emsdk}`;

			const buildRoot = join(onnxruntimeRoot, 'build', 'Linux', 'Release');

			const artifactOutDir = join(root, 'artifact');
			await Deno.mkdir(artifactOutDir);

			const artifactLibDir = join(artifactOutDir, 'onnxruntime', 'lib');
			await Deno.mkdir(artifactLibDir, { recursive: true });

			await Deno.copyFile(join(buildRoot, 'libonnxruntime_webassembly.a'), join(artifactLibDir, 'libonnxruntime.a'));

			return; // Early return.
		}

		const compilerFlags = [];
		const args = [];

		args.push('-Donnxruntime_CLIENT_PACKAGE_BUILD=ON');
		// args.push('-Donnxruntime_MINIMAL_BUILD=ON');
		// args.push('-Donnxruntime_EXTENDED_MINIMAL_BUILD=ON');
		// args.push('-DONNX_MINIMAL_BUILD=ON');
		
		if (platform === 'darwin') {
			args.push('-Dprotobuf_BUILD_PROTOC_BINARIES=OFF');
			args.push(`-DCMAKE_OSX_DEPLOYMENT_TARGET=${options.iphoneos || options.iphonesimulator ? IPHONE_DEPLOYMENT_TARGET : MACOS_DEPLOYMENT_TARGET}`);
			if(options.iphoneos) {
				args.push('-DCMAKE_OSX_SYSROOT=iphoneos');
			} else if(options.iphonesimulator) {
				args.push('-DCMAKE_OSX_SYSROOT=iphonesimulator');
			}
			if(options.iphoneos || options.iphonesimulator) {
				args.push('-DCMAKE_TOOLCHAIN_FILE=../cmake/onnxruntime_ios.toolchain.cmake');
			}
		}

		// TODO: Add nnapi execution provider.
		// ANDROID_NDK_HOME and ANDROID_SDK_ROOT are expected to be set.
		if (platform === 'linux' && options.android) {
			const android_abi = "arm64-v8a"; // TODO: Argument?
			const android_api = 29; // TODO: Argument?
			const android_ndk_path = Deno.env.get("ANDROID_NDK_HOME");
			args.push('-Donnxruntime_ENABLE_LTO=ON');
			args.push(`-DANDROID_PLATFORM=android-${android_api}`);
			args.push(`-DANDROID_ABI=${android_abi}`);
			args.push(`-DANDROID_MIN_SDK=${android_api}`);
			args.push('-DANDROID_USE_LEGACY_TOOLCHAIN_FILE=false');
			args.push(`-DCMAKE_TOOLCHAIN_FILE=${os.path.join(android_ndk_path, "build", "cmake", "android.toolchain.cmake")}`);
		}

		if (platform === 'win32' && options.directml) {
			args.push('-Donnxruntime_USE_DML=ON');
		}
		if (platform === 'darwin' && options.coreml) {
			args.push('-Donnxruntime_USE_COREML=ON');
		}
		if (options.xnnpack) {
			args.push('-Donnxruntime_USE_XNNPACK=ON');
		}
		if (options.webgpu) {
			args.push('-Donnxruntime_USE_WEBGPU=ON');
			args.push('-Donnxruntime_ENABLE_DELAY_LOADING_WIN_DLLS=OFF');
			// args.push('-Donnxruntime_USE_EXTERNAL_DAWN=OFF');
			// args.push('-Donnxruntime_BUILD_DAWN_MONOLITHIC_LIBRARY=ON');
		}
		if (options.openvino && (platform === 'win32' || platform === 'linux')) {
			// OpenVINO probably not available on macOS: https://github.com/microsoft/onnxruntime/issues/24273
			args.push('-Donnxruntime_USE_OPENVINO=ON');
			args.push('-Donnxruntime_USE_OPENVINO_GPU=ON');
			args.push('-Donnxruntime_USE_OPENVINO_CPU=ON');
			args.push('-Donnxruntime_USE_OPENVINO_NPU=ON');
			args.push('-Donnxruntime_DISABLE_RTTI=OFF');
			// args.push('-Donnxruntime_USE_OPENVINO_INTERFACE=ON'); <- Not sure what this does.
		}

		// if (platform === 'darwin') {
		// 	if (options.arch === 'aarch64') {
		// 		args.push('-DCMAKE_OSX_ARCHITECTURES=arm64');
		// 	} else {
		// 		args.push('-DCMAKE_OSX_ARCHITECTURES=x86_64');
		// 	}
		// } else {
		// 	if (options.arch === 'aarch64' && arch !== 'arm64') {
		// 		args.push('-Donnxruntime_CROSS_COMPILING=ON');
		// 		switch (platform) {
		// 			case 'win32':
		// 				args.push('-A', 'ARM64');
		// 				compilerFlags.push('_SILENCE_ALL_CXX23_DEPRECATION_WARNINGS');
		// 				break;
		// 			case 'linux':
		// 				args.push(`-DCMAKE_TOOLCHAIN_FILE=${join(root, 'toolchains', 'aarch64-unknown-linux-gnu.cmake')}`);
		// 				break;
		// 		}
		// 	}
		// }

		if (platform === 'win32') {
			args.push(`-DONNX_USE_MSVC_STATIC_RUNTIME=${options.mt ? 'ON' : 'OFF'}`);
			args.push(`-Dprotobuf_MSVC_STATIC_RUNTIME=${options.mt ? 'ON' : 'OFF'}`);
			args.push(`-Dgtest_force_shared_crt=${options.mt ? 'OFF' : 'ON'}`);
			args.push(`-DCMAKE_MSVC_RUNTIME_LIBRARY=${options.mt ? 'MultiThreaded' : 'MultiThreadedDLL'}`);
			args.push(`-DABSL_MSVC_STATIC_RUNTIME=${options.mt ? 'ON' : 'OFF'}`);
		}

		if (!options.static) {
			args.push('-Donnxruntime_BUILD_SHARED_LIB=ON');
		}

		// https://github.com/microsoft/onnxruntime/pull/21005
		if (platform === 'win32') {
			compilerFlags.push('_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR');
		}

		args.push('-Donnxruntime_BUILD_UNIT_TESTS=OFF');
		args.push('-Donnxruntime_USE_KLEIDIAI=ON');

		if (compilerFlags.length > 0) {
			const allFlags = compilerFlags.map(def => `-D${def}`).join(' ');
			args.push(`-DCMAKE_C_FLAGS=${allFlags}`);
			args.push(`-DCMAKE_CXX_FLAGS=${allFlags}`);
		}

		if (options.ninja) {
			args.push('-G', 'Ninja');
		}

		const sourceDir = options.static ? join(root, 'src', 'static-build') : 'cmake';
		const artifactOutDir = join(root, 'artifact', 'onnxruntime');

		await $`cmake -S ${sourceDir} -B build -D CMAKE_BUILD_TYPE=Release -DCMAKE_CONFIGURATION_TYPES=Release -DCMAKE_INSTALL_PREFIX=${artifactOutDir} -DONNXRUNTIME_SOURCE_DIR=${onnxruntimeRoot} --compile-no-warning-as-error ${args}`;
		await $`cmake --build build --config Release --parallel ${cpus().length}`;
		await $`cmake --install build`;
	})
	.parse(Deno.args);
