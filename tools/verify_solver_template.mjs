import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load('templates/GENORA_template.xlsx'));
console.log((await workbook.inspect({kind:'table',range:'Pengaturan!A16:C17',include:'values',tableMaxRows:2,tableMaxCols:3})).ndjson);
const preview = await workbook.render({sheetName:'Pengaturan',range:'A12:C17',scale:1,format:'png'});
await fs.writeFile('tools/previews/Solver.png',new Uint8Array(await preview.arrayBuffer()));
