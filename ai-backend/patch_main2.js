const fs = require('fs');

const path = '/Users/deeksha_ramakrishna/Desktop/portfolio-deeksha/ai-backend/main.py';
let data = fs.readFileSync(path, 'utf8');

const oldB = `    except WebSocketDisconnect:
        pass`;
const newB = `    except WebSocketDisconnect:
        pass
    except Exception as general_error:
        print("UNHANDLED WEBSOCKET ERROR:", general_error)`;

data = data.replace(oldB, newB);
fs.writeFileSync(path, data);
