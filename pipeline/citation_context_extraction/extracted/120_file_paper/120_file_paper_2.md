画像说明
パノラマX線画像
This image is a panoramic dental radiograph displaying the entire dentition, maxillary and mandibular arches, and surrounding anatomical structures. Task: Analyze the image to identify dental anomalies such as missing teeth, periodontitis, caries, cystic lesions, or temporomandibular joint (TMJ) disorders. Important: Pay particular attention to the number and position of teeth.
頭部正面 X 線画像
This image is a posteroanterior cephalometric radiograph showing the craniofacial skeleton from the front. Task: Assess the symmetry of facial structures, including the maxilla (upper jaw) and mandible (lower jaw). If applicable, detect any canting of the maxilla or lateral deviation of the chin.
頭部側面 X 線画像
This image is a lateral cephalometric radiograph depicting the skull in profile, including the cranial base, cervical spine, maxilla, mandible, and dentition. Assess skeletal and dental relationships in both the anteroposterior and vertical dimensions, with a focus on: Anteroposterior and vertical jaw relationships Mandibular dimensions (effective length, ramus height, body length) Mandibular plane angle (high or low) ANB angle (maxillary protrusion or mandibular prognathism) Anterior and posterior facial heights (upper/lower) Incisor inclinations (maxillary and mandibular) Airway space Classify findings if relevant (e.g., Class II, Class III, vertical discrepancy).

<div style="text-align: center;">図3: VLMに与える画像説明</div>


るために，本研究では VLM に与える指示に FDI 表記の補足を追加する.（図 2“Instructions”の 3 件目）また，X 線画像の種類や用途を明示するために，VLM に与える指示文に画像の説明を含める．本研究では，図 3 に示すように，歯科矯正学の専門知識を有する著者の 1 人が記述した画像説明を用いる．

### 3.3 画像に関する工夫：余白除去

本研究で使用する X 線画像には，データ収集時のリサイズ処理により余白が付与されている．この余白は多くの場合，境界が明瞭な黒色であるが，境界が曖昧な灰色の場合も存在する．VLM がこれらの余白を意味のある特徴として誤認識することを抑制するため，本研究では，画素値の統計情報とエッジ情報を組み合わせた適応的な余白除去を実施する．この前処理により，境界が不鮮明なケースを含め，多様な背景パターンを持つ画像から関心領域のみを抽出して VLM に入力できる．

## 4 評価実験

矯正歯科治療の所見文書から症状をマルチラベル分類する自動診断の実験を通して，X線画像を用いるVLMの有効性およびマルチモーダル自動診断における提案手法の有効性を検証する.

### 4.1 実験設定

データセット 先行研究 [1-4] と同様に，大阪大学歯学部附属病院に所蔵されている 716 件の矯正歯科治療に関する所見文書と，対応する 3 種類の X 線画像（画像サイズは 512 × 512）を用いた。所見文書は 652～8,733 トークン（平均 2,859 トークン）で構成されており，それぞれの所見文書に対して 295 種類の症状ラベルの中から複数のラベル（平均 12 ラベル）が付与されている。データセットは，訓練用・検証用・評価用で 8:1:1 に分割して使用した。

モデル データセットには患者の個人情報が含まれるため，情報漏洩のリスクを考慮し，実験にはローカル VLM を使用した．公正な比較のために，先行研究 [3,4] で用いられた Qwen2.5² [12] の LLM に基づく VLM である Qwen2.5-VL-32B-Instruct³ [18] を使用④した．効率的な訓練のために，QLoRA チューニング [19] を採用し，訓練には Unsloth⁵