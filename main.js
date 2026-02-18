const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');
const crypto = require('crypto');

let flaskProcess = null;
let mainWindow = null;

const FLASK_PORT = 5050;
const FLASK_URL = `http://127.0.0.1:${FLASK_PORT}/`;

function getFlaskPath() {
  if (app.isPackaged) {
    // Production: PyInstaller binary is in extraResources
    const resourcesPath = process.resourcesPath;
    if (process.platform === 'win32') {
      return path.join(resourcesPath, 'sharelink-server', 'sharelink-server.exe');
    } else {
      return path.join(resourcesPath, 'sharelink-server', 'sharelink-server');
    }
  }
  return null; // Development mode — handled separately
}

function getUserDataDir() {
  if (app.isPackaged) {
    return path.dirname(process.execPath);
  }
  return __dirname;
}

function ensureEnvFile() {
  const userDataDir = getUserDataDir();
  const envPath = path.join(userDataDir, '.env');

  if (!fs.existsSync(envPath)) {
    const secretKey = crypto.randomBytes(32).toString('hex');
    const envContent = `SECRET_KEY=${secretKey}\nFLASK_DEBUG=false\nUSE_CLOUD_STORAGE=false\n`;
    fs.writeFileSync(envPath, envContent);
    console.log('Created default .env file at', envPath);
  }
}

function startFlask() {
  const flaskPath = getFlaskPath();

  if (flaskPath) {
    // Production: spawn the PyInstaller binary
    flaskProcess = spawn(flaskPath, [], {
      cwd: getUserDataDir(),
      env: { ...process.env, FLASK_DEBUG: 'false' },
      stdio: ['pipe', 'pipe', 'pipe']
    });
  } else {
    // Development: spawn python app.py using the project venv
    const isWin = process.platform === 'win32';
    const pythonPath = isWin
      ? path.join(__dirname, 'venv', 'Scripts', 'python.exe')
      : path.join(__dirname, 'venv', 'bin', 'python3');
    const appPath = path.join(__dirname, 'app.py');

    flaskProcess = spawn(pythonPath, [appPath], {
      cwd: __dirname,
      stdio: ['pipe', 'pipe', 'pipe']
    });
  }

  flaskProcess.stdout.on('data', (data) => {
    console.log(`Flask: ${data}`);
  });

  flaskProcess.stderr.on('data', (data) => {
    console.error(`Flask: ${data}`);
  });

  flaskProcess.on('close', (code) => {
    console.log(`Flask process exited with code ${code}`);
    flaskProcess = null;
  });
}

function waitForFlask(retries = 30, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      attempts++;
      http.get(FLASK_URL, (res) => {
        resolve();
      }).on('error', () => {
        if (attempts >= retries) {
          reject(new Error('Flask server did not start in time'));
        } else {
          setTimeout(check, interval);
        }
      });
    };
    check();
  });
}

function killFlask() {
  if (flaskProcess) {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', flaskProcess.pid.toString(), '/f', '/t']);
    } else {
      flaskProcess.kill('SIGTERM');
    }
    flaskProcess = null;
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      partition: 'persist:sharelink'
    }
  });

  ensureEnvFile();
  startFlask();

  try {
    await waitForFlask();
    mainWindow.loadURL(FLASK_URL);
    mainWindow.show();
  } catch (err) {
    console.error('Failed to start Flask server:', err.message);
    killFlask();
    app.quit();
  }
}

app.whenReady().then(createWindow);

app.on('before-quit', () => {
  killFlask();
});

app.on('window-all-closed', () => {
  killFlask();
  app.quit();
});
