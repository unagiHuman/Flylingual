// Reproducible, dependency-free frontend packaging. Does not modify the Bridge.
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Script } from 'node:vm';

const root=dirname(fileURLToPath(import.meta.url));
let html=await readFile(join(root,'index.html'),'utf8');
let css=await readFile(join(root,'styles.css'),'utf8');
const sprite=await readFile(join(root,'assets/moods.png'));
css=css.replace("url('assets/moods.png')",()=>"url('data:image/png;base64,"+sprite.toString('base64')+"')");
html=html.replace('<link rel="stylesheet" href="styles.css">',()=>'<style>'+css+'</style>');
for(const name of ['core.js','audio.js','video.js','settings.js','app.js']) {
  const source=await readFile(join(root,name),'utf8');
  new Script(source,{filename:name});
  html=html.replace('<script src="'+name+'" defer></script>','');
  html=html.replace('</body>',()=>'<script>\n'+source.replace(/<\/script/gi,'<\\/script')+'\n</script>\n</body>');
}
if(/(?:src|href)="(?:assets\/|styles\.css|core\.js|audio\.js|app\.js|video\.js|settings\.js)/.test(html)||/url\(['"]?assets\//.test(html))throw new Error('Unbundled local resource');
await mkdir(join(root,'dist'),{recursive:true});
await writeFile(join(root,'dist/player.html'),html);
console.log('Created '+join(root,'dist/player.html')+' ('+Buffer.byteLength(html)+' bytes)');
