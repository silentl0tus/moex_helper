import http from "http";
import fs from "fs"
import { constants } from "buffer";

const host = "localhost"
const port = "3001"

const server = http.createServer((req, res) => {
    const { method, url } = req

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (method === 'OPTIONS') {
        res.writeHead(200);
        res.end();
        return;
    }

    if (method === 'GET' && url === '/'){
        res.writeHead(200, "OK", { 'content-type': 'string'})
        res.end("hello world")
    }
    if (method === 'POST' && url === '/'){
        try{
            let body = '';
            
            req.on('data', (chunk) => {
                body += chunk.toString();
            })
            
            req.on('end', () => {
                console.log('Received body length:', body.length)

                const jsonData = JSON.parse(body);
                console.log(jsonData.table[0]["ticket"])

                fs.writeFile(`./files/${jsonData.table[0]["ticket"]}.json`, JSON.stringify(jsonData.table[0]["report"], null, 2), (err) => {
                    if (err) {
                        console.error('File save error:', err);
                        res.writeHead(500, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ error: 'Failed to save file' }));
                        return;
                    }
                    console.log('The file has been saved!');
                    
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ 
                        message: 'Data received and saved successfully',
                        status: 'ok'
                    }));
                })
            })
        }
        catch (err){
            console.error('Error:', err);
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: err.message }));
        }
    }

    if (method === "GET" && url.startsWith("/files/")) {
        const ticket = url.split('/')[2]?.replace('.json', '');
        
        if (!ticket) {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Ticket name is required' }));
            return;
        }
        
        const filePath = `./files/${ticket}.json`;
        
        fs.access(filePath, fs.constants.F_OK, (err) => {
            if (err) {
                res.writeHead(404, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: `File ${ticket}.json not found` }));
                return;
            }
            
            fs.readFile(filePath, 'utf8', (err, data) => {
                if (err) {
                    res.writeHead(500, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: 'Cannot read file' }));
                    return;
                }
                
                res.setHeader('Content-Disposition', `attachment; filename="${ticket}.json"`);
                res.setHeader('Content-Type', 'application/json');
                res.writeHead(200);
                res.end(data);
            });
        });
    }

}).listen(port, host, () => {
  console.log(`Server running at http://${host}:${port}/`);
})