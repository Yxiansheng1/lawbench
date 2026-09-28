// Offline assets builder. Run from the package root with: go run tools/build.go
package main

import (
 "crypto/sha256"
 "encoding/base64"
 "encoding/hex"
 "encoding/json"
 "fmt"
 "os"
 "path/filepath"
 "strings"
)

func must(err error) { if err != nil { panic(err) } }
func main() {
 templates := []map[string]any{}
 docs := map[string]string{}
 sourceFiles := []map[string]string{}
 // 重建前清空副本目录：本脚本只写不删，若分组调整（如由「个人-固定」改为「个人委托」），
 // 旧分组会残留在 resources/templates 下，造成副本与内置数据不一致的误读。
 must(os.RemoveAll(filepath.Join("resources","templates")))
 must(filepath.WalkDir("original-skill", func(path string, d os.DirEntry, err error) error {
  if err != nil { return err }; if d.IsDir() { if d.Name()=="__pycache__" { return filepath.SkipDir }; return nil }
  rel,_:=filepath.Rel("original-skill",path); rel=filepath.ToSlash(rel)
  if d.Name()==".DS_Store" || strings.HasPrefix(d.Name(),"~$") { return nil }
  b,e:=os.ReadFile(path); if e!=nil{return e}; h:=sha256.Sum256(b)
  sourceFiles=append(sourceFiles,map[string]string{"path":rel,"sha256":hex.EncodeToString(h[:])})
  if strings.HasSuffix(rel,".docx") {
   parts:=strings.Split(rel,"/"); name:=parts[len(parts)-1]; group:=parts[len(parts)-2]
   tag:="checklist"
   if strings.Contains(name,"合同"){tag="contract"} else if strings.Contains(name,"授权"){tag="auth"} else if strings.Contains(name,"身份证明"){tag="legalrep"} else if strings.Contains(name,"所函"){tag="letter"} else if strings.Contains(name,"会见"){tag="meeting_letter"}
   templates=append(templates,map[string]any{"id":group+"/"+name,"group":group,"name":name,"tag":tag,"base64":base64.StdEncoding.EncodeToString(b),"sha256":hex.EncodeToString(h[:]),"builtin":true})
   dest:=filepath.Join("resources","templates",group,name); must(os.MkdirAll(filepath.Dir(dest),0755)); must(os.WriteFile(dest,b,0644))
  } else if strings.HasSuffix(rel,".md") || strings.HasSuffix(rel,".json") || strings.HasSuffix(rel,".py") { docs[rel]=string(b) }
  return nil
 }))
 if len(templates)!=13 { panic(fmt.Sprintf("expected 13 templates, got %d",len(templates))) }
 appDocs:=map[string]string{}
 paths,e:=filepath.Glob("docs/*.md");must(e);paths=append(paths,"使用说明.md","CHANGELOG.md")
 for _,path:=range paths {b,e:=os.ReadFile(path);must(e);appDocs[filepath.ToSlash(path)]=string(b)}
 data:=map[string]any{"version":"3.4.0","sourceVersion":"3.2.0","templates":templates,"originalDocs":docs,"appDocs":appDocs,"sourceFiles":sourceFiles}
 b,e:=json.Marshal(data); must(e); must(os.WriteFile("data/builtin.js",append([]byte("window.RETAINER_BUILTIN="),append(b,[]byte(";\n")...)...),0644))
 pretty,e:=json.MarshalIndent(sourceFiles,"","  ");must(e);must(os.WriteFile("data/source-manifest.json",pretty,0644))
 // Source data is JSON; browser uses an equivalent local script to work under file://.
 for _,name:=range []string{"config","rules"} {
  raw,e:=os.ReadFile("data/"+name+".json");must(e); var parsed any;must(json.Unmarshal(raw,&parsed)); out,e:=json.Marshal(parsed);must(e)
  must(os.WriteFile("data/"+name+".js",append([]byte("window.RETAINER_"+strings.ToUpper(name)+"="),append(out,[]byte(";\n")...)...),0644))
 }
 fmt.Println(fmt.Sprintf("Built %d templates, original skill contents and local data scripts",len(templates)))
}
