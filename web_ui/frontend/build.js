const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');
const sourceDir = path.join(root, 'web');
const distDir = path.join(__dirname, 'dist');

function copyFile(src, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function copyTree(srcDir, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
    const srcPath = path.join(srcDir, entry.name);
    const destPath = path.join(destDir, entry.name);
    if (entry.isDirectory()) {
      copyTree(srcPath, destPath);
    } else if (entry.isFile()) {
      copyFile(srcPath, destPath);
    }
  }
}

fs.rmSync(distDir, { recursive: true, force: true });
copyTree(sourceDir, distDir);
console.log(`Built frontend from ${sourceDir} to ${distDir}`);
