import Foundation

func runPython(setName: String) -> (output: String, exitCode: Int32) {
    let scriptPath = FileManager.default.currentDirectoryPath + "/python/tcg_analyzer.py"
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    process.arguments = ["python3", scriptPath, setName]

    let outputPipe = Pipe()
    let errorPipe = Pipe()
    process.standardOutput = outputPipe
    process.standardError = errorPipe

    do {
        try process.run()
    } catch {
        return ("Failed to run Python: \(error)", -1)
    }

    process.waitUntilExit()

    let outData = outputPipe.fileHandleForReading.readDataToEndOfFile()
    let errData = errorPipe.fileHandleForReading.readDataToEndOfFile()
    var output = String(data: outData, encoding: .utf8) ?? ""
    let errOutput = String(data: errData, encoding: .utf8) ?? ""
    if !errOutput.isEmpty {
        if !output.isEmpty { output += "\n" }
        output += "[stderr]\n" + errOutput
    }
    return (output, process.terminationStatus)
}

let setName: String
if CommandLine.arguments.count > 1 {
    setName = CommandLine.arguments.dropFirst().joined(separator: " ")
} else {
    print("Enter Pokémon set name:", terminator: " ")
    if let input = readLine(), !input.isEmpty {
        setName = input
    } else {
        print("No set name provided; exiting.")
        exit(1)
    }
}

print("Running analyzer for set: \(setName)")
let (output, exitCode) = runPython(setName: setName)
print("--- Analyzer Output ---\n")
print(output)
if exitCode != 0 {
    fputs("\nPython process exited with code \(exitCode)\n", stderr)
}
