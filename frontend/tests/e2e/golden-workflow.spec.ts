import {expect,test} from "@playwright/test";
test("seeded role can traverse the golden workflow",async({page})=>{
  await page.goto("/"); await page.getByLabel("Email").fill("quality@magnotherm.test"); await page.getByLabel("Password").fill("magnotherm"); await page.getByRole("button",{name:"Sign in"}).click();
  await expect(page.getByRole("heading",{name:"Engineering operations"})).toBeVisible();
  for(const route of ["/procurement","/qms","/ecm","/controlling","/knowledge","/approval-inbox"]){await page.goto(route);await expect(page.locator("h1")).toBeVisible()}
});
