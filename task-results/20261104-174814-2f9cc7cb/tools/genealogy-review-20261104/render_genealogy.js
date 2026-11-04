/** 把系谱图版面转换为可逐项编辑的原生文本和连线。 */
const fs = require('fs');
const path = require('path');
const pptxgen = require(process.argv[4] || 'pptxgenjs');

async function writeDeck(source, pages, output) {
  const deck = new pptxgen();
  deck.defineLayout({name: '系谱打印', width: source.width / 72, height: source.height / 72});
  deck.layout = '系谱打印';
  deck.author = '';
  deck.subject = '按主稿分户制作的系谱核对图';
  deck.title = '村志分户系谱图';
  deck.company = '';
  deck.lang = 'zh-CN';
  deck.theme = {headFontFace: '黑体', bodyFontFace: '宋体', lang: 'zh-CN'};
  for (const page of pages) {
    const slide = deck.addSlide();
    slide.background = {color: 'FFFFFF'};
    for (const atom of page.atoms) {
      if (atom.kind === 'line') {
        const x = Math.min(atom.x1, atom.x2), y = Math.min(atom.y1, atom.y2);
        if (Math.abs(atom.x2 - atom.x1) + Math.abs(atom.y2 - atom.y1) < 0.01) continue;
        slide.addShape(deck.ShapeType.line, {
          x: x / 72, y: y / 72, w: Math.abs(atom.x2 - atom.x1) / 72, h: Math.abs(atom.y2 - atom.y1) / 72,
          flipH: atom.x2 < atom.x1, flipV: atom.y2 < atom.y1,
          line: {color: '111827', width: atom.width, dashType: atom.dashed ? 'dash' : 'solid'},
          objectName: '亲属关系连线'
        });
      } else {
        slide.addText(atom.text, {
          x: atom.x / 72, y: atom.y / 72, w: atom.w / 72, h: atom.h / 72,
          fontFace: atom.bold ? '黑体' : '宋体', fontSize: atom.size, bold: atom.bold,
          margin: 0, breakLine: false, valign: 'top', align: atom.align,
          color: '111827', lang: 'zh-CN', paraSpaceAfterPt: 0,
          objectName: '人物或系谱标注', isTextBox: true
        });
      }
    }
    slide.addNotes('原文人物条目：' + page.record_ids.join('、') + '。本户第' + page.local_page + '页，共' + page.local_total + '页。');
  }
  await deck.writeFile({fileName: output});
}

async function main() {
  const source = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  await writeDeck(source, source.pages, process.argv[3]);
  const splitDirectory = process.argv[5];
  if (splitDirectory) {
    fs.mkdirSync(splitDirectory, {recursive: true});
    for (let i = 0; i < source.houses.length; i++) {
      const house = source.houses[i];
      const safe = house[1].replace(/[<>:"/\\|?*]/g, '').slice(0, 45);
      const filename = String(i + 1).padStart(2, '0') + '_' + house[0] + '_' + safe + '.pptx';
      await writeDeck(source, source.pages.filter(p => p.house_id === house[0]), path.join(splitDirectory, filename));
    }
  }
  process.stdout.write('已生成可编辑系谱图，共' + source.pages.length + '页。\n');
}
main().catch(error => { process.stderr.write(String(error.stack) + '\n'); process.exit(1); });
