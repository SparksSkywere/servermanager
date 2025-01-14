@{
    RootModule = 'ServerManager.psm1'
    ModuleVersion = '1.0.0'
    GUID = '12345678-1234-1234-1234-123456789012'
    Author = 'SkywereIndustries'
    Description = 'Server Manager Module'
    PowerShellVersion = '5.1'
    # Remove any NestedModules or ScriptsToProcess that might reference private paths
    FunctionsToExport = '*'
    CmdletsToExport = '*'
    VariablesToExport = '*'
    AliasesToExport = '*'
}
