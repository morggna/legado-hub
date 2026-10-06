import React from "react"
import { createRoot } from "react-dom/client"
import { MemoryRouter, Routes, Route } from "react-router"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { DirectReaderPage } from "../src/routes/DirectReaderPage"
import "../src/index.css"

const titles = ["第一回　宴桃园豪杰三结义　斩黄巾英雄首立功", "第二回　张翼德怒鞭督邮　何国舅谋诛宦竖", "第三回　议温明董卓叱丁原　馈金珠李肃说吕布"]
const texts = [
  "滚滚长江东逝水，浪花淘尽英雄。是非成败转头空。青山依旧在，几度夕阳红。\n\n白发渔樵江渚上，惯看秋月春风。一壶浊酒喜相逢。古今多少事，都付笑谈中。\n\n话说天下大势，分久必合，合久必分。周末七国分争，并入于秦。及秦灭之后，楚、汉分争，又并入于汉。汉朝自高祖斩白蛇而起义，一统天下，后来光武中兴，传至献帝，遂分为三国。\n\n推其致乱之由，殆始于桓、灵二帝。桓帝禁锢善类，崇信宦官。及桓帝崩，灵帝即位，大将军窦武、太傅陈蕃，共相辅佐。\n\n当时宦官曹节等弄权，窦武、陈蕃谋诛之，机事不密，反为所害，中涓自此愈横。\n\n建宁二年四月望日，帝御温德殿。方升座，殿角狂风骤起，只见一条大青蛇，从梁上飞将下来，蟠于椅上。帝惊倒，左右急救入宫，百官俱奔避。\n\n须臾，蛇不见了。忽然大雷大雨，加以冰雹，落到半夜方止，坏却房屋无数。\n\n建宁四年二月，洛阳地震；又海水泛溢，沿海居民，尽被大浪卷入海中。\n\n光和元年，雌鸡化雄。六月朔，黑气十余丈，飞入温德殿中。秋七月，有虹现于玉堂，五原山岸，尽皆崩裂。种种不祥，非止一端。",
  "且说董卓字仲颖，陇西临洮人也，官拜河东太守，自来骄傲。\n\n当日怠慢了玄德，张飞性发，便欲杀之。玄德与关公急止之曰：\n\n“他是朝廷命官，岂可擅杀？”\n\n飞曰：“若不杀这厮，反要在他部下听令，其实不甘！二兄要便住在此，我自投别处去也。”\n\n玄德曰：“我三人义同生死，岂可相离？不若都投别处去便了。”\n\n飞曰：“若如此，稍解吾恨。”\n\n于是三人连夜引军来投朱儁。儁待之甚厚，合兵一处，进讨张宝。",
  "却说曹操当日对何进曰：“宦官之祸，古今皆有；但世主不当假之权宠，使至于此。\n\n若欲治罪，当除元恶，但付一狱吏足矣，何必纷纷召外兵乎？欲尽诛之，事必宣露。吾料其必败也。”\n\n何进怒曰：“孟德亦怀私意耶？”\n\n操退曰：“乱天下者，必进也。”\n\n进乃暗差使命，赍密诏星夜往各镇去。"
]
let progress = {chapterIndex: 0, position: 0, revision: 0}
window.fetch = async (input, init) => {
  const path = String(input)
  let body: unknown = {}
  if (path.endsWith("/progress")) {
    if (init?.method === "PUT") progress = {...JSON.parse(String(init.body)), revision: progress.revision + 1}
    body = progress
  } else if (path.endsWith("/detail")) body = {bookId: "preview", name: "三国演义", author: "罗贯中", sourceName: "阅读器原型 · 示例正文"}
  else if (path.endsWith("/toc")) body = {chapters: titles.map((title, index) => ({title, index}))}
  else if (path.includes("/chapters/")) {
    const index = Number(path.split("/").pop())
    body = {index, title: titles[index], content: texts[index]}
  }
  return new Response(JSON.stringify(body), {status: 200, headers: {"Content-Type": "application/json"}})
}
const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
createRoot(document.getElementById("root")!).render(<React.StrictMode><QueryClientProvider client={client}><MemoryRouter initialEntries={["/console/library/preview"]}><Routes><Route path="/console/library/:bookId" element={<DirectReaderPage />} /><Route path="*" element={<div className="p-8">这是阅读器原型。<a href="/visual-diff/reader-preview.html" className="underline">返回示例阅读</a></div>} /></Routes></MemoryRouter></QueryClientProvider></React.StrictMode>)
