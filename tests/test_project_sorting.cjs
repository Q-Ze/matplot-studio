const { test } = require("node:test");
const assert = require("node:assert/strict");
const { sortPlots } = require("../web/project-sorting.js");

test("name sorting is natural, stable, and leaves source order intact", () => {
  const plots = [{name:"Figure 10"},{name:"Figure 2"},{name:"Figure 1"}];
  assert.deepEqual(sortPlots(plots,"name-asc").map(p=>p.name),["Figure 1","Figure 2","Figure 10"]);
  assert.deepEqual(sortPlots(plots,"name-desc").map(p=>p.name),["Figure 10","Figure 2","Figure 1"]);
  assert.deepEqual(sortPlots(plots,"original"),plots);
  assert.equal(plots[0].name,"Figure 10");
  const equal = [{name:"a",id:1},{name:"A",id:2}];
  assert.deepEqual(sortPlots(equal,"name-asc"),equal);
});

test("modification sorting handles both directions, ties, missing dates, and updates", () => {
  const plots = [{name:"unknown"},{name:"old",raw:{modified_at:10}},
    {name:"new",raw:{modified_at:20}},{name:"tie",raw:{modified_at:20}}, {name:"null",raw:{modified_at:null}}];
  assert.deepEqual(sortPlots(plots,"modified-desc").map(p=>p.name),["new","tie","old","unknown","null"]);
  assert.deepEqual(sortPlots(plots,"modified-asc").map(p=>p.name),["old","new","tie","unknown","null"]);
  plots[1].raw.modified_at = 30;
  assert.equal(sortPlots(plots,"modified-desc")[0].name,"old");
});
