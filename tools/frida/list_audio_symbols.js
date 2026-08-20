const module = Process.getModuleByName("libaudioclient.so");
const matches = module.enumerateSymbols().filter(symbol => symbol.name.indexOf("AudioRecord") !== -1 && (symbol.name.indexOf("obtainBuffer") !== -1 || symbol.name.indexOf("setE") !== -1 || symbol.name.endsWith("AudioRecord4stopEv")));
send(matches.map(symbol => ({name: symbol.name, address: symbol.address.toString()})));
