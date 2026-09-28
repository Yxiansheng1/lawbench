import fs from 'node:fs/promises';
import {FileBlob,SpreadsheetFile} from 'file:///C:/Users/0/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('D:/test codex/retainer-offline/标准案件录入.xlsx'));
console.log((await wb.inspect({kind:'table',range:"'示例勿作正式案件'!A1:L4",include:'values',tableMaxRows:4,tableMaxCols:12})).ndjson);
for(const [sheet,range,name]of [['案件录入','A1:L3','input'],['填写说明','A1:B9','instructions'],['示例勿作正式案件','A1:L4','examples']]){
 const image=await wb.render({sheetName:sheet,range,scale:1.4});await fs.writeFile('D:/test codex/retainer-qa/xlsx-'+name+'.png',new Uint8Array(await image.arrayBuffer()));
}
