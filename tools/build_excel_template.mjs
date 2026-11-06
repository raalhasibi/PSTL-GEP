import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const seed = JSON.parse(await fs.readFile(new URL('./template_seed.json', import.meta.url), 'utf8'));
const workbook = Workbook.create();
const col = n => { let s=''; for (; n>0; n=Math.floor((n-1)/26)) s=String.fromCharCode(65+(n-1)%26)+s; return s; };
for (const [name, matrix] of Object.entries(seed)) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const last = col(matrix[0].length);
  sheet.getRange(`A1:${last}${matrix.length}`).values = matrix;
  const range = sheet.getRange(`A1:${last}${matrix.length}`);
  range.format.font = { name: 'Arial', size: 10, color: '#172C42' };
  range.format.rowHeight = 21;
  range.format.columnWidth = 22;
  range.format.verticalAlignment = 'center';
  sheet.getRange(`A1:${last}1`).format = { fill:'#24415E', font:{name:'Arial', size:10, bold:true, color:'#FFFFFF'}, wrapText:true, rowHeight:45 };
  sheet.freezePanes.freezeRows(1);
  if (matrix.length > 1) sheet.getRange(`A2:${last}${matrix.length}`).setNumberFormat('0.00');
  if (name === 'Petunjuk') {
    sheet.getRange(`A2:A${matrix.length}`).format.font.bold = true;
    sheet.getRange(`A1:A${matrix.length}`).format.columnWidth = 30;
    sheet.getRange(`B1:B${matrix.length}`).format.columnWidth = 125;
    sheet.getRange(`B2:B${matrix.length}`).format.wrapText = true;
    sheet.getRange(`A2:B${matrix.length}`).format.rowHeight = 36;
  } else if (name === 'Pengaturan') {
    sheet.getRange(`A1:A${matrix.length}`).format.columnWidth = 44;
    sheet.getRange(`B1:B${matrix.length}`).format.columnWidth = 46;
    sheet.getRange(`B2:B${matrix.length}`).format.fill = '#FFF3CD';
    sheet.getRange('B2:B4').setNumberFormat('0');
    sheet.getRange(`C1:C${matrix.length}`).format.columnWidth = 91;
    for (const row of [5]) sheet.getRange(`B${row}`).dataValidation = {rule:{type:'list', values:['Kontinu (LP)','Blok integer (MILP)','Blok integer + penyimpanan (MILP)']}};
    for (const row of [10,12]) sheet.getRange(`B${row}`).dataValidation = {rule:{type:'list',values:['YA','TIDAK']}};
    sheet.getRange('B13').dataValidation = {rule:{type:'list',values:['Pertumbuhan tahunan','Manual per tahun']}};
    for (const row of [14,15]) sheet.getRange(`B${row}`).dataValidation = {rule:{type:'list',values:['Gunakan data tahun dasar','Edit per tahun']}};
    sheet.getRange('B16').dataValidation = {rule:{type:'list',values:['HiGHS','Gurobi']}};
    sheet.getRange('B17').dataValidation = {rule:{type:'list',values:['Komputer/server (lisensi terpasang)','Cloud (WLS)']}};
  } else {
    if (matrix.length > 1) sheet.getRange(`A2:${last}${matrix.length}`).format.font.color = '#1556A0';
    if (name === 'Kapasitas Eksogen') {
      sheet.getRange('A2:A1000').setNumberFormat('0');
      sheet.getRange('C1:C1000').format.columnWidth = 30;
      sheet.getRange('C2:C1000').dataValidation = {rule:{type:'decimal',operator:'greaterThanOrEqual',formula1:0}};
    }
    if (name === 'Pembangkit' || name === 'Penyimpanan') {
      sheet.getRange(`A1:${last}${matrix.length}`).format.columnWidth = 28;
      sheet.getRange(`A1:${last}1`).format.rowHeight = 60;
      sheet.getRange('A1:A100').format.columnWidth = 23;
    }
    if (name === 'Profil Beban') {
      sheet.getRange('A2:B1000').setNumberFormat('0');
      sheet.getRange('C1:C1000').format.columnWidth = 29;
      sheet.getRange('C2:C1000').dataValidation = {rule:{type:'decimal',operator:'between',formula1:0,formula2:100}};
    }
    if (name === 'Availability') {
      sheet.getRange('A2:B1000').setNumberFormat('0');
      sheet.getRange('D2:D1000').setNumberFormat('0.0000');
      sheet.getRange('D2:D1000').dataValidation = {rule:{type:'decimal',operator:'between',formula1:0,formula2:1}};
    }
    if (name === 'Beban Puncak') sheet.getRange('A2:A1000').setNumberFormat('0');
    if (name === 'Stokastik') {
      sheet.getRange('C1:C1000').format.columnWidth = 45;
      sheet.getRange('B2:B1000').setNumberFormat('0.0000');
    }
  }
}
workbook.recalculate();
console.log((await workbook.inspect({kind:'table',range:'Pengaturan!A1:C5',include:'values',tableMaxRows:5,tableMaxCols:3})).ndjson);
await fs.mkdir(new URL('../templates/',import.meta.url), {recursive:true});
await fs.mkdir(new URL('./previews/',import.meta.url), {recursive:true});
for (const name of Object.keys(seed)) {
  const last = col(seed[name][0].length);
  const preview = await workbook.render({sheetName:name,range:`A1:${last}${Math.min(seed[name].length,6)}`,scale:1,format:'png'});
  await fs.writeFile(new URL(`./previews/${name.replaceAll(' ','_')}.png`,import.meta.url),new Uint8Array(await preview.arrayBuffer()));
}
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:10}})).ndjson);
await (await SpreadsheetFile.exportXlsx(workbook)).save(new URL('../templates/GENORA_template.xlsx',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1'));
