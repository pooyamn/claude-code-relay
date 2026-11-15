$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'topic-receipt-admission.ps1')
$script:checks=0;$id='11111111111111111111111111111111';$later='22222222222222222222222222222222'
function Check($value,$name){if(-not $value){throw $name};$script:checks++}
function Json($value){ConvertTo-Json -InputObject $value -Depth 8 -Compress}
$params=[ordered]@{threadId='11111111-1111-4111-8111-111111111111';cwd='/work/target';excludeTurns=$true;approvalPolicy='never';approvalsReviewer='user';permissions=':danger-full-access'}
$ack=@{thread=@{id=$params.threadId;cwd=$params.cwd};approvalPolicy='never'}
$script:rows=[string[][]](,[string[]]@($later,(Json $ack)))
$read={param($sql) Check ($sql.Contains('n.rowid>o.rowid') -and $sql.Contains("n.status='confirmed'") -and $sql.Contains("json_extract(n.payload,'$.parameters')=json_extract(o.payload,'$.parameters')")) 'Exact later confirmed parameters required'; ,$script:rows}
Check ([bool](Get-TopicReceiptSupersession $id 'native/thread/resume' (Json @{parameters=$params}) $read)) 'Identical later native ACK is supersession, not confirmation'
foreach($mode in @('extra','missing','false','string-true','wrong-type','bad-id','empty-cwd','wrong-case')){
 $value=[ordered]@{};foreach($key in $params.Keys){$value[$key]=$params[$key]}
 switch($mode){
  extra {$value.input='run work'} missing {$value.Remove('permissions')}
  false {$value.excludeTurns=$false} string-true {$value.excludeTurns='true'}
  wrong-type {$value.permissions=123} bad-id {$value.threadId='bad'}
  empty-cwd {$value.cwd=' '} wrong-case {$value.Remove('permissions');$value.Permissions=':danger-full-access'}
 }
 Check (-not (Get-TopicReceiptSupersession $id 'native/thread/resume' (Json @{parameters=$value}) $read)) ('Reject malformed resume '+$mode)
}
foreach($mode in @('id','cwd','policy')){
 $bad=@{thread=@{id=$params.threadId;cwd=$params.cwd};approvalPolicy='never'}
 switch($mode){id {$bad.thread.id='22222222-2222-4222-8222-222222222222'} cwd {$bad.thread.cwd='/work/other'} policy {$bad.approvalPolicy='on-request'}}
 $script:rows=[string[][]](,[string[]]@($later,(Json $bad)))
 Check (-not (Get-TopicReceiptSupersession $id 'native/thread/resume' (Json @{parameters=$params}) $read)) ('Reject mismatched ACK '+$mode)
}
$script:rows=[string[][]]@()
Check (-not (Get-TopicReceiptSupersession $id 'native/thread/resume' (Json @{parameters=$params}) $read)) 'No later ACK remains blocking'
foreach($kind in @('native/turn/start','native/turn/steer','native/thread/fork','telegram/sendMessage','claude/input')){
 Check (-not (Get-TopicReceiptSupersession $id $kind (Json @{parameters=$params}) $read)) ('Never supersede model/output action '+$kind)
}
$menu=@{scope=@{type='chat_member';chat_id=-100123;user_id=123};commands=@(@{command='status';description='Status'})}
$script:rows=[string[][]](,[string[]]@($later,'true'))
$menuRead={param($sql) Check ($sql.Contains('n.rowid>o.rowid') -and $sql.Contains("n.status='confirmed'") -and $sql.Contains('n.payload=o.payload') -and $sql.Contains("n.result='true'")) 'Exact later menu ACK query'; ,$script:rows}
Check ([bool](Get-TopicReceiptSupersession $id 'telegram/setMyCommands' (Json $menu) $menuRead)) 'Identical later menu ACK'
foreach($mode in @('extra','scope-extra','wrong-scope','bad-chat','bad-user','bad-commands')){
 $bad=(Json $menu)|ConvertFrom-Json
 switch($mode){extra {$bad|Add-Member input 'run work'} scope-extra {$bad.scope|Add-Member topic 42} wrong-scope {$bad.scope.type='default'} bad-chat {$bad.scope.chat_id=123} bad-user {$bad.scope.user_id=0} bad-commands {$bad.commands='bad'}}
 Check (-not (Get-TopicReceiptSupersession $id 'telegram/setMyCommands' (Json $bad) $menuRead)) ('Reject malformed menu '+$mode+' '+(Json $bad))
}
$script:rows=[string[][]]@()
Check (-not (Get-TopicReceiptSupersession $id 'telegram/setMyCommands' (Json $menu) $menuRead)) 'No exact later menu ACK remains blocking'
Check (-not (Get-TopicReceiptSupersession 'sql-injection' 'native/thread/resume' (Json @{parameters=$params}) $read)) 'Reject nonliteral operation ID'
Check (-not (Get-TopicReceiptSupersession $id 'native/thread/resume' '{bad' $read)) 'Malformed JSON fails closed'
Check ((ConvertTo-Json -InputObject ([string[][]]@()) -Depth 100 -Compress) -ceq '[]') 'Empty held-receipt snapshot remains a serializable array'
"Passed $script:checks topic receipt admission checks (inert fixtures; no network, native input or production writes)."
