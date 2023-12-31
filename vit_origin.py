# -*- coding: utf-8 -*-
"""VIT_origin

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1KWXTQ7qJozFUvtrHvrJuhkP3a77tl9r9
"""

!pip install einops

#einops는 텐서 연산을 수행하는 라이브러리로
#다양한 라이브러리에서 사용할 수 있는 직관적인 구문을 제공하여 텐서의 차원을 다루는 작업을 쉽게 만들어줍니다.
#특히 딥러닝에서 많이 사용되는 PyTorch, TensorFlow, JAX 등의 프레임워크와 함께 사용할 수 있습니다.

#einops를 사용하면 여러 차원을 조작하는 데 유용한 다양한 기능을 제공합니다.
#예를 들어, rearrange 함수는 PyTorch의 permute, reshape, transpose와 유사한 기능을 제공합니다.
#하지만 einops의 경우 사용하기 편리하고 직관적인 표기법을 사용하여 텐서의 차원을 변경하는 작업을 더 쉽게 수행할 수 있습니다.

#또한 einops는 복잡한 딥러닝 모델에서 많이 사용되는 수많은 텐서 차원 조작과 연산을 단순하고 직관적인 표기법으로 표현할 수 있습니다.
#이렇게 하면 코드를 작성하고 디버깅하는 것이 훨씬 쉬워지며, 텐서 차원을 조작하는 작업에서 발생하는 많은 오류를 방지할 수 있습니다.

import torch
import torch.nn.functional as F
import matplotlib.pyplot as plt

from torch import nn
from torch import Tensor
from PIL import Image
from torchvision.transforms import Compose, Resize, ToTensor
from einops import rearrange, reduce, repeat
from einops.layers.torch import Rearrange, Reduce
from torchsummary import summary

"""# **PatchEmbedding 클래스**"""

class PatchEmbedding(nn.Module):
  def __init__(self, in_channels:int=3, patch_size:int=16,
               emb_size:int=768, img_size:int=224):
      super().__init__()

      self.patch_size = patch_size

      #1,2.단계
      self.projection = nn.Sequential(
          Rearrange('b c (h p1) (w p2) -> b (h w) (p1 p2 c)', p1=patch_size, p2=patch_size),
          nn.Linear(patch_size * patch_size * in_channels, emb_size)
      )

      #클래스 토큰 생성
      self.cls_token = nn.Parameter(torch.randn(1,1,emb_size))

      #Position 생성
      self.positions = nn.Parameter(torch.randn((img_size//patch_size)**2+1, emb_size))

  def forward(self, x):

      b, c, h, w = x.shape

      #1,2,3단계
      x = self.projection(x)

      #4. 클래스 토큰 추가
      ## 배치사이즈만큼의 개수의 클래스 토큰이 필요하기 때문에 repeat으로 반복
      cls_tokens = repeat(self.cls_token, '() n e -> b n e', b=b)
        #repeat() : 주어진 텐서를 반복하여 새로운 텐서를 생성하는 함수
        #self.cls_token 값을 b번 반복하여 cls_tokens라는 이름의 텐서를 생성한다.
        #두번째 인자는 출력 텐서의 모양 지정
          #():축이름, 여기서는 인덱스 0에 해당하는 축
          #n:데이터 샘플의 개수
          #e:임베딩차원을 나타내는 축
        #인덱스 0에 해당하는 축을 비워둔 상태에서 데이터 샘플의 개수는 b로, 임베딩 차원은 self.cls_token의 임베딩 차원과 같게 변환한다는 뜻
      ## 클래스 토큰을 x에 concate 시켜준다.
      x = torch.cat([cls_tokens, x], dim=1)


      #5. Position 더하기
      x += self.positions

      return x

#torchsummary : PyTorch 모델의 요약 정보를 보여주는 유용한 도구
#모델의 총 파라미터 수, 각 레이어의 입력/출력 shape, 메모리 사용량 등의 정보를 제공
#summary() : 모델 객체와 입력 데이터의 shape을 함수에 전달

PE = PatchEmbedding()
summary(PE, (3, 224, 224), device='cpu')

"""# **MultiHeadAttention 클래스**"""

class MultiHeadAttention(nn.Module):
  def __init__(self, emb_size=768, num_heads=8, drop_rate=0):
      super().__init__()

      self.emb_size = emb_size
      self.num_heads = num_heads

      self.query = nn.Linear(emb_size, emb_size)
      self.key = nn.Linear(emb_size, emb_size)
      self.value = nn.Linear(emb_size, emb_size)

      self.att_dropout = nn.Dropout(drop_rate)

      self.projection = nn.Linear(emb_size, emb_size)

  def forward(self, x:Tensor, mask:Tensor=None) -> Tensor :

      #1. k,q,v를 head 개수만큼 나눈다.
      q = rearrange(self.query(x), "b n (h d) -> b h n d", h=self.num_heads)
      k = rearrange(self.key(x), "b n (h d) -> b h n d", h=self.num_heads)
      v = rearrange(self.value(x), "b n (h d) -> b h n d", h=self.num_heads)

      #2.a 쿼리 키 MatMul
      energy = torch.einsum("bhqd, bhkd -> bhqk", q, k)

      if mask is not None:
        fill_value = torch.finfo(torch.float32).min#float32 유형에서 가장 작은 값
        energy.mask_fill(~mask, fill_value)#마스크가 적용되지 않은 값을 fill_value 값으로 채운다
        #마스크가 있는 경우 energy 텐서의 일부분을 최소값으로 채워서, 해당 부분의 값이 가중합에 영향을 미치지 않도록 합니다.

      #2.b scale
      scale = self.emb_size ** (1/2)

      #2.c attention 스코어 구하기
      att = F.softmax(energy / scale, dim=-1)

      #2.d attention 스코어에 dropout 적용
      att = self.att_dropout(att)

      #2.e Attention value 구하기
      out = torch.einsum("bhal, bhlv -> bhav", att, v)

      #2.f 각 헤드에서 처리한 결과 합치고 원래 차원으로 되돌리기
      out = rearrange(out, "b h n d -> b n (h d)")
      out = self.projection(out)

      return out

x = torch.randn(8, 3, 224, 224)
PE = PatchEmbedding()
x = PE(x)
print(x.shape)
MHA = MultiHeadAttention()
summary(MHA, x.shape[1:], device='cpu')

"""# **Transformer의 Encoder Layer**"""

class TFencoderLayer(nn.Module):

    def __init__(self, emb_size:int=768, num_heads:int=8, mlp_hidden_dim=768*4, drop_rate:int=0):
        super().__init__()

        #1. Layer Normalization 생성
        #LayerNormalization : 입력텐서의 각 feature에 대한 평균과 표준편차를 구하고, 이를 사용해서 입력값을 Normalize
        #Tranformer의 Encoder에서 Normalization은 두 번 사용되므로 두 개 정의
        self.ln1 = nn.LayerNorm(emb_size)
        self.ln2 = nn.LayerNorm(emb_size)

        #2. MSA 생성
        #Multi-head self-attention
        self.msa = MultiHeadAttention(emb_size=emb_size, num_heads=num_heads, drop_rate=drop_rate)
        #위에서 정의한 클래스 사용
        #입력값을 각각의 head에 대해 다른 weight로 attention score를 계산한 후 이를 합쳐서 하나의 output으로 만든다.
        #이 때, emb_size는 입력 텐서의 feature 크기
        #num_heads는 Multi-headed attention에서 head의 개수


        #dropout
        self.dropout = nn.Dropout(drop_rate)
        #drop_rate는 드롭아웃을 적용할 확률입니다.

        #3. Residual Connection -> 아래 forward함수에서 적용

        #4. Layer Normalization -> 아래 forward함수에서 적용

        #5. MLP layer 생성
        #MLP(Multi-Layer Perceptron)
        #FC Layer를 두 개 사용하고, Activation func.은 GELU 함수를 사용한다.
        self.mlp = nn.Sequential(nn.Linear(emb_size, mlp_hidden_dim), #첫번째 FC layer : 출력 벡터의 형태는 두 번째 FC Layer의 입력벡터 크기로
                                 nn.GELU(), #활성화 함수로 GELU 사용
                                 nn.Dropout(drop_rate), #Dropout 적용
                                 nn.Linear(mlp_hidden_dim, emb_size), #두번째 FC layer :
                                 nn.Dropout(drop_rate)) #Dropout 용

        ##6. Residual Connection 아래 forward함수에서 적용
    def forward(self, x):
        #Layer Normalization 적용
        z = self.ln1(x)

        #MultiheadedSelfAttention의 forward 메서드를 통해 Attention 값을 계산
        z = self.msa(z)

        #Dropout 적용
        z = self.dropout(z)

        #원래의 입력값과 Dropout 적용 값 더하기
        x = x + z

        #Layer Normalization 적용
        z = self.ln2(x)

        #MLP통과
        z = self.mlp(z)

        #원래의 입력값과 MLP 통과시킨 값 더하기
        #입력값 x가 더 깊은 층으로 전달될 때, 이전 층에서 처리된 정보를 보존하면서 새로운 정보를 추가할 수 있습니다.
        x = x + z

        return x

x = torch.randn(8, 3, 224, 224)
x = PE(x)
x = MHA(x)
TE = TFencoderLayer()
summary(TE, x.shape[1:], device='cpu')

"""# **ViT 모델 구현**"""

class VisionTransformer(nn.Sequential):
    def __init__(self, in_channels: int = 3, patch_size: int = 16, emb_size: int = 768,
                 num_heads: int = 8, img_size: int = 224, mlp_hidden_dim: int =768*4,
                 drop_rate: int =0, num_layers: int =12, n_classes: int = 1000):

        super().__init__()

        #1. patchembedding 생성
        self.patchembedding = PatchEmbedding(in_channels=in_channels, patch_size=patch_size,
                                               emb_size=emb_size, img_size=img_size)

        #2. transformer 생성
        self.transformer = nn.ModuleList([TFencoderLayer(emb_size=emb_size, num_heads=num_heads,
                                                         mlp_hidden_dim=mlp_hidden_dim, drop_rate=drop_rate)
                                          for _ in range(num_layers)])
        #3. mlp_head 생성
        self.mlp_head = nn.Sequential(
            nn.LayerNorm(emb_size),
            nn.Linear(emb_size, n_classes)
            )

    def forward(self, x):

        #이미지는 패치 (Patch)로 분할되어 패치 임베딩에 의해 각 패치는 임베딩 벡터로 변환
        x = self.patchembedding(x)

        #임베딩 된 패치는 Transformer Encoder Layer를 통해 인코딩
        #각 Transformer Encoder Layer는 Multi-Head Self-Attention 및 MLP Layer의 조합으로 구성
        for layer in self.transformer:
            x = layer(x)

        #인코딩 된 이미지 벡터는 MLP Head Layer를 통해 최종적으로 분류
        x = self.mlp_head(x[:,0])

        return x

summary(VisionTransformer(patch_size=4,img_size=32,emb_size=4*4*3,mlp_hidden_dim=4*4*3*4,num_layers=4,n_classes=10), (3, 32, 32), device='cpu')

!pip3 install torchvision

#필요한 라이브러리 import
from torchvision import datasets
from torchvision import transforms
import torchvision

#학습데이터
##학습데이터(train_dataset)에 적용할 transform(data augmentation)정의
transform_train = transforms.Compose([
    transforms.RandomCrop(32, padding=4),
    transforms.ToTensor()
])

##학습데이터(train_dataset)불러오기
train_dataset = datasets.CIFAR10(
      root = './data',
      train = True,
      download = True,
      transform = transform_train
)


#테스트데이터
##테스트데이터(test_dataset)에 적용할 transform정의
transform_test = transforms.ToTensor()

##테스트데이터(test_dataset)불러오기
test_dataset = datasets.CIFAR10(
    root = './data',
    train = False,
    download = True,
    transform = transform_test
)

train_dataset

test_dataset

from torch.utils.data import DataLoader

#학습데이터
train_dataloader = DataLoader(train_dataset, batch_size=128, shuffle=True, num_workers=2)

#테스트데이터
test_dataloader = DataLoader(test_dataset, batch_size=128, shuffle=False, num_workers=2)

#사용할 디바이스
device = 'cuda'
model=VisionTransformer(patch_size=4,img_size=32,emb_size=4*4*3,mlp_hidden_dim=4*4*3*4,num_layers=4,n_classes=10)
#모델을 디바이스에 로드
model = model.to(device)

from torch import optim
from torch.optim import lr_scheduler

#손실함수
loss_fn = nn.CrossEntropyLoss()

#optimizer
optimizer = optim.SGD(model.parameters(),lr=0.1, momentum=0.9, weight_decay=0.0001)

#학습률 조정
scheduler = lr_scheduler.MultiStepLR(optimizer, milestones=[50,100], gamma=0.1)

def train_loop(epoch):
    #몇번째 epoch인지를 나타내기 위해 출력하고 시작
    print('\n[ Train epoch: %d ]' % epoch)

    #학습모드 설정(모델이 학습중임을 알려주는데 사용)
    model.train()

    #데이터 개수 초기화
    total = 0
    #loss 초기화
    train_loss = 0
    #정확하게 예측한 데이터의 개수 초기화
    correct = 0

    #targets pre

    optimizer.step()
    scheduler.step()

    for batch, (inputs, targets) in enumerate(train_dataloader):
        #dataloader에서 batch_size=128로 설정했기 때문에
        #한 번의 루프(iteration)에서 128개의 데이터가 처리되고 반환된다.
        #train_dataset은 50000개의 데이터가 있기 때문에
        #50000/128=391개의 배치가 생성되고 루프(iteration)가 391번 돌아감

        #입력데이터와 타켓(정답)데이터를 GPU로 옮김
        inputs = inputs.to(device)
        targets = targets.to(device)

        #순전파
        ##예측
        preds = model(inputs) #preds에는 10개의 클래스에 대한 예측확률값이 들어있음
        _, predicted = preds.max(1) #가장 큰 확률값을 가지는 클래스를 반환해서 예측값을 predicted에 저장

        ##loss계산
        loss = loss_fn(preds, targets)

        #역전파(Backpropagation)
        ##weight initialization : 기울기를 0으로 초기화
        optimizer.zero_grad()
        ##위에서 계산한 loss를 바탕으로 gradient 계산
        loss.backward()
        ##가중치 업데이트
        optimizer.step()


        ##현재 배치에서의 loss랑 accuracy를 확인
        ###정확하게 예측한 데이터의 개수
        current_correct = predicted.eq(targets).sum().item()
        #current_correctP = predictedP.eq(targets).sum().item()

          #eq() : predicted와 targets값을 비교해서 같으면 1(True), 다르면 0(False)로 이루어진 텐서 객체 반환
          #eq().sum() : True값이 1이니까 더하면 정확하게 예측한 데이터 개수
          #그런데 sum()까지하면 이 값은 텐서 객체 값이기 때문에
          #item() : 텐서 객체 값을 정수나 부동소수점으로 변환해주는 함수

        ###100배치마다 정확도와 loss 출력
        if batch % 100 == 0 :
            #현재 배치
            print('\nCurrent batch:', str(batch))
            #현재 배치에서의 훈련 정확도의 평균
            #print('Current batch average train accuracy_P:', current_correctP / targetsP.size(0))
            print('Current batch average train accuracy:', current_correct / targets.size(0))
            #현재 배치에서의 손실 평균
            #print('Current batch average train loss_P:', loss2.item() / targetsP.size(0))
            print('Current batch average train loss:', loss.item() / targets.size(0))

        ##전체(1 epoch)에서 loss랑 accuracy 확인
        ###데이터 개수 누적 > 현재 진행되고 있는 배치에서 사용되는 데이터의 개수가 누적된다
        total += targets.size(0)
          #targets는 미니배치 크기인 128개의 타깃 데이터가 포함된 1차원 텐서 (128,)
          #각 iteration때마다 데이터 개수를 누적시킴
        ###loss 누적 > 현재 진행되고 있는 배치에서 사용되는 데이터의 개수가 누적된다
        train_loss += loss.item()
        ###정확하게 예측한 데이터의 개수 누적 > 현재 진행되고 있는 배치에서 사용되는 데이터의 개수가 누적된다
        correct += current_correct
    #1epoch마다 평균accuracy랑 평균 loss확인, top-5 accuracy 확인
    print('\nTotal average train accuarcy:', correct / total)
    print('Total average train loss:', train_loss / total)
    #print('Top-5 train accuracy:', top5_correct / total)

    return [correct / total, train_loss/total]

import os



def test_loop(epoch):
    #몇번째 epoch인지를 나타내기 위해 출력하고 시작
    print('\n[ Test epoch: %d ]' % epoch)

    #테스트모드 설정(모델이 테스트 중임을 알려주는데 사용)
    model.eval()

    #데이터 개수 초기화
    total = 0
    #loss 초기화
    test_loss = 0
    #정확하게 예측한 데이터의 개수 초기화
    correct = 0


    for batch, (inputs, targets) in enumerate(test_dataloader):
        #dataloader에서 batch_size=128로 설정했기 때문에
        #한 번의 루프(iteration)에서 128개의 데이터가 처리되고 반환된다.
        #test_dataset은 10000개의 데이터가 있기 때문에
        #10000/128=79개의 배치가 생성되고 루프(iteration)가 79번 돌아감

        #입력데이터와 타켓(정답)데이터를 GPU로 옮김
        inputs = inputs.to(device)
        targets = targets.to(device)

        #순전파
        ##예측
        preds = model(inputs) #preds에는 10개의 클래스에 대한 예측확률값이 들어있음
        _, predicted = preds.max(1) #가장 큰 확률값을 가지는 클래스를 반환해서 예측값을 predicted에 저장
        ##loss계산
        loss = loss_fn(preds, targets)


        #logging : 잘 진행되고 있는지 체크하기 위해서 ...
        ##전체(1epoch)에서 loss랑 accuracy 확인
        ###데이터 개수 누적 > 현재 진행되고 있는 배치에서 사용되는 데이터의 개수가 누적된다
        total += targets.size(0)
          #targets는 미니배치 크기인 128개의 타깃 데이터가 포함된 1차원 텐서 (128,)
          #각 iteration때마다 데이터 개수를 누적시킴

        #loss 누적 > 현재 진행되고 있는 배치에서 사용되는 데이터의 개수가 누적된다
        test_loss += loss.item()

        ###정확하게 예측한 데이터의 개수 누적 > 현재 진행되고 있는 배치에서 사용되는 데이터의 개수가 누적된다
        correct += predicted.eq(targets).sum().item()

        #top5_error = torch.mean((correct_top5 == 0).float())
        #top1_error = torch.mean((correct_top1 == 0).float())
    #1 epoch마다 평균accuracy랑 평균 loss확인
    print('\nTotal average train accuarcy:', correct / total)
    print('Total average train loss:', test_loss / total)


    #학습된 모델의 파라미터를 파일로 저장
    #학습된 모델의 파라미터를 저장하기 위해서 딕셔너리 생성
    state = {
        'model': model.state_dict()
        #model.state_dict() : 모델의 모든 파라미터를 담고 있는 딕셔너리 객체
    }

    #학습된 모델의 파라미터를 파일로 저장하는 과정
    if not os.path.isdir('checkpoint'): #checkpoint라는 디렉토리가 존재하지 않으면
        os.mkdir('checkpoint') #새로생성
        #즉, checkpoint 디렉토리에는 학습된 모델의 파라미터를 저장할 파일이 위치

    #state 변수를 파일로 저장
    file_name = 'resnet18_cifar10.pth'
    torch.save(state, './checkpoint/' + file_name)
      #파일 경로는 './checkpoint/' + file_name
    #저장완료 후 저장완료 메시지 출력
    print('Model Saved!')

    return [correct / total, test_loss / total]

import time

import torch, gc
gc.collect()
torch.cuda.empty_cache()

start_time = time.time()

train_losses = []
train_accuracies = []
test_losses = []
test_accuracies = []


for epoch in range(0, 300):

    #학습(train)
    x=train_loop(epoch)

    #학습(train) logging값 저장
    train_losses.append(x[1])
    train_accuracies.append(x[0])

    #테스트(test)
    y=test_loop(epoch)

    #학습(train) logging값 저장
    test_losses.append(y[1])
    test_accuracies.append(y[0])

    #매 에폭이 끝날때마다 학습에 소요된 시간을 계산해서(현재시간 - 시작시간) 출력
    print('\nTime elapsed:', time.time() - start_time)

!tar -cvf 서버에서 돌린 로그파일을 tar로 압축저장하여 다운받기위한 명령어
!tar -xvf /content/runs.tar 다운받은 tar을 다시 폴더로 압축해제 하는 명령어

print(test_accuracies)
print(train_accuracies)

!pip install tensorboard

# Commented out IPython magic to ensure Python compatibility.
# %reload_ext tensorboard
# %tensorboard --logdir=./NNN/runs/