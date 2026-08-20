/* Rooted Emulator Experiment candidate: replace AudioRecord PCM in one process. */

const targetLibrary = "libaudioclient.so";
const sourcePath = "/data/local/tmp/ushareiplay-source.pcm";
let source = new Uint8Array(0);
let sourceAvailable = false;
try {
  const sourceFile = new File(sourcePath, "rb");
  source = sourceFile.readBytes();
  sourceFile.close();
  sourceAvailable = source.byteLength > 0;
} catch (error) {
  send({ event: "source-unavailable", source: sourcePath, error: String(error) });
}
let sourceOffset = 0;

function findSymbol(name) {
  const module = Process.getModuleByName(targetLibrary);
  const knownAndroid30Offsets = {
    "_ZN7android11AudioRecord12obtainBufferEPNS0_6BufferEPK8timespecPS3_Pm": 0x553ec,
  };
  if (knownAndroid30Offsets[name] !== undefined) {
    return module.base.add(knownAndroid30Offsets[name]);
  }
  const symbols = module.enumerateSymbols();
  for (const symbol of symbols) {
    if (symbol.name === name) return symbol.address;
  }
  throw new Error("symbol not found: " + name);
}

function copySource(destination, size) {
  if (!sourceAvailable) return;
  let remaining = size;
  while (remaining > 0) {
    const available = source.byteLength - sourceOffset;
    const count = Math.min(remaining, available);
    destination.writeByteArray(source.slice(sourceOffset, sourceOffset + count));
    destination = destination.add(count);
    remaining -= count;
    sourceOffset = (sourceOffset + count) % source.byteLength;
  }
}

const obtainBuffer = findSymbol("_ZN7android11AudioRecord12obtainBufferEPNS0_6BufferEPK8timespecPS3_Pm");
Interceptor.attach(obtainBuffer, {
  onEnter(args) {
    this.buffer = args[1];
  },
  onLeave(retval) {
    if (retval.toInt32() !== 0 || this.buffer.isNull()) return;
    const size = this.buffer.add(Process.pointerSize).readU64().toNumber();
    const raw = this.buffer.add(Process.pointerSize * 2).readPointer();
    if (size > 0 && !raw.isNull()) {
      copySource(raw, size);
      send({ event: "AudioRecord::obtainBuffer", bytes: size });
    }
  },
});

send({ event: "hook-installed", library: targetLibrary, source: sourcePath, sourceAvailable });
