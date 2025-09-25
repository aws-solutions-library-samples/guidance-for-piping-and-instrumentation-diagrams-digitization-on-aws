# Shared Files Automation

This document describes the automated system for sharing common utilities between Lambda functions in the P&ID Digitization Pipeline.

## Overview

The pipeline uses a shared file synchronization system to avoid code duplication across Lambda functions. Common utilities like configuration helpers, coordinate transformations, and execution path management are maintained in a central location and automatically copied to Lambda function directories during development.

## Architecture

### Shared Files Location
- **Source**: `cdk/lambda/shared/`
- **Target**: Individual Lambda function directories (`cdk/lambda/*/`)

### Automation Script
- **Script**: `cdk/scripts/sync-shared-files.js`
- **Execution**: Automatically run during development and before deployment
- **Language**: Node.js for cross-platform compatibility

## Shared Utilities

### Current Shared Files

1. **`config_helper.py`**
   - Configuration loading and validation
   - S3-based configuration management
   - Used by: All Lambda functions

2. **`coordinate_transform.py`** 
   - Coordinate space transformations
   - Image processing coordinate conversion
   - Used by: GraphGenerator, SymbolDetection

3. **`execution_paths.py`**
   - S3 execution-based file organization
   - Consistent path generation across pipeline stages
   - Used by: All Lambda functions

### File Mapping

The synchronization system uses a mapping in `lambda.ts` to specify which shared files each Lambda function needs:

```typescript
const sharedFileMapping: { [key: string]: string[] } = {
  'input_validator': ['config_helper.py'],
  'text_detection': ['config_helper.py'], 
  'graph_generator': ['config_helper.py', 'coordinate_transform.py'],
  'symbol_detection': ['config_helper.py', 'coordinate_transform.py'],
  'notes_processor': ['config_helper.py'],
};
```

## Sync Process

### Manual Synchronization
```bash
cd cdk
node scripts/sync-shared-files.js
```

### Automatic Synchronization
- Triggered before CDK deployments
- Part of the build process for Docker-based Lambda functions
- Integrated with development workflows

### Sync Logic
1. **Source Scanning**: Identifies all `.py` files in `cdk/lambda/shared/`
2. **Target Identification**: Maps files to Lambda functions based on configuration
3. **File Copying**: Copies required files to each Lambda function directory
4. **Change Detection**: Only copies files that have been modified
5. **Cleanup**: Removes outdated shared files from Lambda directories

## Benefits

### Code Maintenance
- **Single Source of Truth**: Common utilities maintained in one location
- **Consistency**: All Lambda functions use identical shared code
- **Version Control**: Changes to shared utilities automatically propagate

### Development Efficiency
- **No Manual Copying**: Automated synchronization prevents human error
- **Reduced Duplication**: Shared utilities exist only once in the repository
- **Easy Updates**: Modify shared code once, deploy everywhere

### Deployment Safety
- **Self-Contained**: Each Lambda function directory contains all required code
- **No Runtime Dependencies**: No cross-Lambda dependencies during execution
- **Rollback Safety**: Each deployment is complete and independent

## File Structure

```
cdk/
├── lambda/
│   ├── shared/              # Source of truth for shared utilities
│   │   ├── config_helper.py
│   │   ├── coordinate_transform.py
│   │   └── execution_paths.py
│   ├── input_validator/     # Target directories
│   │   ├── index.py
│   │   └── config_helper.py # Copied from shared/
│   ├── text_detection/
│   │   ├── index.py
│   │   └── config_helper.py # Copied from shared/
│   └── ...
└── scripts/
    └── sync-shared-files.js  # Automation script
```

## Development Workflow

### Adding New Shared Files
1. Create the file in `cdk/lambda/shared/`
2. Update the file mapping in `cdk/lib/constructs/lambda.ts`
3. Run the sync script: `node scripts/sync-shared-files.js`
4. Test with affected Lambda functions

### Updating Shared Files
1. Modify the file in `cdk/lambda/shared/`
2. Run the sync script: `node scripts/sync-shared-files.js`
3. Test all affected Lambda functions
4. Deploy changes

### Best Practices
- **Keep Shared Files Pure**: Avoid Lambda-specific logic in shared utilities
- **Version Compatibility**: Ensure shared files work across all Python 3.13 runtimes
- **Documentation**: Document shared utility APIs clearly
- **Testing**: Test shared utilities independently before integration

## Troubleshooting

### Common Issues

**Sync Script Fails**
```bash
# Check Node.js version
node --version

# Run with verbose output
node scripts/sync-shared-files.js --verbose
```

**Shared File Not Found**
- Verify file exists in `cdk/lambda/shared/`
- Check file mapping in `lambda.ts`
- Run sync script manually

**Import Errors**
- Ensure shared files use relative imports
- Check Python path configuration
- Verify file synchronization completed

### Manual Recovery
If automatic synchronization fails, you can manually copy files:

```bash
# Copy specific shared file to all Lambda functions
for dir in cdk/lambda/*/; do
  if [ -f "$dir/index.py" ]; then
    cp cdk/lambda/shared/config_helper.py "$dir/"
  fi
done
```

## Future Enhancements

### Planned Improvements
- **Dependency Tracking**: Automatic detection of shared file dependencies
- **Incremental Sync**: Only sync changed files to reduce deployment time
- **Validation**: Automatic testing of shared file compatibility
- **Version Management**: Support for multiple versions of shared utilities

### Integration Opportunities
- **CI/CD Integration**: Automatic synchronization in build pipelines
- **IDE Support**: Development environment integration for real-time sync
- **Monitoring**: Track shared file usage and update patterns
