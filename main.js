const { app, BrowserWindow } = require('electron');

function createWindow() {
const win = new BrowserWindow({
  width: 1200,
  height: 800,
  webPreferences: {
    nodeIntegration: false,
    contextIsolation: true,
    partition: 'persist:sharelink'
  }
});

  
  // Clear cache and load homepage
  win.webContents.session.clearCache();
  win.loadURL('http://127.0.0.1:5000/');
  win.webContents.openDevTools();
  
  win.webContents.on('did-finish-load', () => {
    console.log('Loaded:', win.webContents.getURL());
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});