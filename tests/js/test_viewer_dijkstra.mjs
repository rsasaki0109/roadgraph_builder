// Extract the two JS functions from docs/js/map_console.js and smoke-test them
// against a tiny fixture that exercises a no_left_turn restriction.
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const thisDir = path.dirname(url.fileURLToPath(import.meta.url));
const src = fs.readFileSync(
  path.resolve(thisDir, '..', '..', 'docs', 'js', 'map_console.js'),
  'utf-8',
);

// Extract function sources by naive slicing. Matches the top-level function
// shapes in docs/js/map_console.js — if the viewer is refactored, adjust here.
function extractFn(name) {
  const re = new RegExp(`function ${name}\\([^\\)]*\\)\\s*\\{`);
  const m = src.search(re);
  if (m < 0) throw new Error('cannot find ' + name);
  let depth = 0;
  let i = src.indexOf('{', m);
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) {
        return 'function ' + name + src.slice(m + 'function '.length + name.length, i + 1);
      }
    }
  }
  throw new Error('unterminated ' + name);
}

const srcBuild = extractFn('buildRestrictionIndex');
const srcDij = extractFn('dijkstra');
const fn = new Function(srcBuild + '\n' + srcDij + '\nreturn {buildRestrictionIndex, dijkstra};');
const {buildRestrictionIndex, dijkstra} = fn();

// Tiny fixture: node graph is an H shape
//   n1 --e1-- n2 --e2-- n3
//              |
//              e3 (down)
//              |
//              n4
// restriction: no_left_turn at n2, from e1 forward, to e3 forward.
// Going n1->n4 via n2 would have to pass through this transition -> banned.
const adj = new Map();
adj.set('n1', [{edge_id:'e1', length:10, neighbor:'n2', reverse:false}]);
adj.set('n2', [
  {edge_id:'e1', length:10, neighbor:'n1', reverse:true},
  {edge_id:'e2', length:10, neighbor:'n3', reverse:false},
  {edge_id:'e3', length:10, neighbor:'n4', reverse:false},
]);
adj.set('n3', [
  {edge_id:'e2', length:10, neighbor:'n2', reverse:true},
  {edge_id:'e4', length:10, neighbor:'n4', reverse:false},
]);
adj.set('n4', [
  {edge_id:'e3', length:10, neighbor:'n2', reverse:true},
  {edge_id:'e4', length:10, neighbor:'n3', reverse:true},
]);
const graph = {adj, nodes: new Map(), edges: new Map()};

// No restrictions: shortest n1 -> n4 is via e1 + e3 -> 20 m.
const rNone = dijkstra(graph, 'n1', 'n4', buildRestrictionIndex([]));
console.log('no TR :', rNone.totalLength, rNone.edges.join(','));
if (rNone.totalLength !== 20) throw new Error('baseline wrong');
if (JSON.stringify(rNone.edges) !== JSON.stringify(['e1','e3'])) throw new Error('baseline path wrong');

// With no_left_turn: must detour via e1+e2+e4 -> 30 m.
const rBanned = dijkstra(graph, 'n1', 'n4', buildRestrictionIndex([
  {
    junction_node_id: 'n2',
    from_edge_id: 'e1',
    from_direction: 'forward',
    to_edge_id: 'e3',
    to_direction: 'forward',
    restriction: 'no_left_turn',
  },
]));
console.log('no_left:', rBanned.totalLength, rBanned.edges.join(','));
if (rBanned.totalLength !== 30) throw new Error('restriction did not force detour');
if (JSON.stringify(rBanned.edges) !== JSON.stringify(['e1','e2','e4'])) throw new Error('detour path wrong');

// only_right_turn: at n2 coming from e1, MUST go to e2 (right). e3 and return
// on e1 both banned. Expected detour via e2+e4 (30 m) — same as no_left_turn
// case but through the whitelist code path.
const rOnly = dijkstra(graph, 'n1', 'n4', buildRestrictionIndex([
  {
    junction_node_id: 'n2',
    from_edge_id: 'e1',
    from_direction: 'forward',
    to_edge_id: 'e2',
    to_direction: 'forward',
    restriction: 'only_right_turn',
  },
]));
console.log('only_rt:', rOnly.totalLength, rOnly.edges.join(','));
if (rOnly.totalLength !== 30) throw new Error('only_ restriction did not force detour');

console.log('OK');
