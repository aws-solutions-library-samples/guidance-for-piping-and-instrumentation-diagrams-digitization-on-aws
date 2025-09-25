#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

// Shared file mapping - defines which shared files each lambda function needs
const sharedFileMapping = {
  'input_validator': ['config_helper.py', 'execution_paths.py'],
  'text_detection': ['config_helper.py', 'execution_paths.py', 'debug_image_utils.py'], 
  'graph_generator': ['config_helper.py', 'coordinate_transform.py', 'execution_paths.py'],
  'symbol_detection': ['config_helper.py', 'coordinate_transform.py', 'execution_paths.py', 'debug_image_utils.py'],
  // line_detection and graph_visualization use Docker and copy directly from shared/ - no sync needed
  'notes_processor': ['config_helper.py', 'execution_paths.py'],
};

const lambdaDir = path.join(__dirname, '../lambda');
const sharedDir = path.join(lambdaDir, 'shared');

console.log('🔄 Synchronizing shared files...');

// Check if shared directory exists
if (!fs.existsSync(sharedDir)) {
  console.error('❌ Shared directory not found:', sharedDir);
  process.exit(1);
}

let totalCopied = 0;
let errors = 0;

// Copy shared files to each lambda function that needs them
Object.entries(sharedFileMapping).forEach(([lambdaFunction, sharedFiles]) => {
  const targetDir = path.join(lambdaDir, lambdaFunction);
  
  if (!fs.existsSync(targetDir)) {
    console.warn(`⚠️  Lambda directory not found: ${lambdaFunction}`);
    return;
  }

  console.log(`\n📁 Processing ${lambdaFunction}:`);
  
  sharedFiles.forEach(file => {
    const sourcePath = path.join(sharedDir, file);
    const targetPath = path.join(targetDir, file);
    
    try {
      // Check if source file exists
      if (!fs.existsSync(sourcePath)) {
        console.error(`  ❌ Source file not found: ${file}`);
        errors++;
        return;
      }

      // Copy file with metadata preservation
      fs.copyFileSync(sourcePath, targetPath);
      
      // Verify copy was successful
      if (fs.existsSync(targetPath)) {
        console.log(`  ✅ ${file} → ${lambdaFunction}/`);
        totalCopied++;
      } else {
        console.error(`  ❌ Failed to copy: ${file}`);
        errors++;
      }
    } catch (error) {
      console.error(`  ❌ Error copying ${file}:`, error.message);
      errors++;
    }
  });
});

console.log('\n📊 Summary:');
console.log(`  ✅ Files copied: ${totalCopied}`);
console.log(`  ❌ Errors: ${errors}`);

if (errors > 0) {
  console.log('\n⚠️  Some files failed to copy. Please check the errors above.');
  process.exit(1);
} else {
  console.log('\n🎉 All shared files synchronized successfully!');
  process.exit(0);
}
