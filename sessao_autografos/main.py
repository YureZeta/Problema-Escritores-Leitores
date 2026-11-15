import sys
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition
from time import sleep

from PySide6.QtCore import (
    QEasingCurve,
    QPauseAnimation,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QPointF,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio import AudioEvento


@dataclass(frozen=True)
class Fa:
    id: int
    nome: str
    aparencia: int


class TravaLeitoresEscritores:
    """Permite leituras simultaneas e escrita exclusiva, priorizando escritores."""

    def __init__(self) -> None:
        self._condicao = Condition()
        self._leitores_ativos = 0
        self._escritor_ativo = False
        self._escritores_esperando = 0

    @contextmanager
    def leitura(self):
        with self._condicao:
            while self._escritor_ativo or self._escritores_esperando > 0:
                self._condicao.wait()
            self._leitores_ativos += 1

        try:
            yield
        finally:
            with self._condicao:
                self._leitores_ativos -= 1
                if self._leitores_ativos == 0:
                    self._condicao.notify_all()

    @contextmanager
    def escrita(self):
        with self._condicao:
            self._escritores_esperando += 1
            try:
                while self._escritor_ativo or self._leitores_ativos > 0:
                    self._condicao.wait()
                self._escritor_ativo = True
            finally:
                self._escritores_esperando -= 1

        try:
            yield
        finally:
            with self._condicao:
                self._escritor_ativo = False
                self._condicao.notify_all()


class LeitorWorker(QThread):
    entrou = Signal(int, int)
    mensagem = Signal(str)
    consulta_concluida = Signal(int, object)

    def __init__(
        self,
        numero: int,
        trava: TravaLeitoresEscritores,
        autografos: list[str],
        duracao_segundos: int,
    ) -> None:
        super().__init__()
        self.numero = numero
        self.trava = trava
        self.autografos = autografos
        self.duracao_segundos = duracao_segundos

    def run(self) -> None:
        self.mensagem.emit(f"Leitor {self.numero} pediu para consultar a lista.")

        with self.trava.leitura():#Região Crítica
            self.entrou.emit(self.numero, self.duracao_segundos)
            self.mensagem.emit(f"Leitor {self.numero} esta lendo a lista.")
            sleep(self.duracao_segundos)
            resultado = tuple(self.autografos)

        self.consulta_concluida.emit(self.numero, resultado)


class AutorWorker(QThread):
    comecou_a_assinar = Signal(int, str)
    mensagem = Signal(str)
    autografo_concluido = Signal(int, str, object)

    def __init__(
        self,
        fa: Fa,
        trava: TravaLeitoresEscritores,
        autografos: list[str],
        duracao_segundos: int,
    ) -> None:
        super().__init__()
        self.fa = fa
        self.trava = trava
        self.autografos = autografos
        self.duracao_segundos = duracao_segundos

    def run(self) -> None:#Região Crítica
        self.mensagem.emit(
            f"O autor aguarda acesso exclusivo para atender {self.fa.nome}."
        )

        with self.trava.escrita():
            self.comecou_a_assinar.emit(self.fa.id, self.fa.nome)
            self.mensagem.emit(f"O autor esta autografando para {self.fa.nome}.")
            sleep(self.duracao_segundos)
            self.autografos.append(self.fa.nome)
            resultado = tuple(self.autografos)

        self.autografo_concluido.emit(self.fa.id, self.fa.nome, resultado)


class PersonagemPixel(QGraphicsObject):
    PIXEL = 4
    LARGURA = 17 * PIXEL
    ALTURA = 25 * PIXEL

    PALETAS = (
        {
            "pele": "#f0b68f",
            "cabelo": "#392b35",
            "camisa": "#4c8f89",
            "detalhe": "#e9c85d",
            "calca": "#3e507b",
            "sapato": "#4c332d",
        },
        {
            "pele": "#d99b76",
            "cabelo": "#472b62",
            "camisa": "#ca668c",
            "detalhe": "#f3d9a1",
            "calca": "#633e72",
            "sapato": "#382c43",
        },
        {
            "pele": "#f4cba3",
            "cabelo": "#d8873e",
            "camisa": "#4187a1",
            "detalhe": "#f2df6f",
            "calca": "#466c75",
            "sapato": "#48352c",
        },
        {
            "pele": "#b8785c",
            "cabelo": "#263d54",
            "camisa": "#bd5967",
            "detalhe": "#f2c8a4",
            "calca": "#455074",
            "sapato": "#332d43",
        },
        {
            "pele": "#edc3a2",
            "cabelo": "#246b78",
            "camisa": "#d68b45",
            "detalhe": "#f4de7a",
            "calca": "#506c58",
            "sapato": "#3b3546",
        },
    )

    def __init__(
        self,
        aparencia: int,
        nome: str | None = None,
        papel: str = "fa",
    ) -> None:
        super().__init__()
        self.aparencia = aparencia % len(self.PALETAS)
        self.estilo_cabelo = aparencia % 4
        self.papel = papel
        self.pose = "parado"
        self.andando = False
        self.quadro = 0
        self.setZValue(10)

        self._rotulo: QGraphicsSimpleTextItem | None = None
        if nome is not None:
            self._rotulo = QGraphicsSimpleTextItem(nome, self)
            self._rotulo.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            self._rotulo.setBrush(QBrush("#fff0c2"))
            largura_texto = self._rotulo.boundingRect().width()
            self._rotulo.setPos((self.LARGURA - largura_texto) / 2, 101)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.LARGURA, 124)

    def set_pose(self, pose: str) -> None:
        self.pose = pose
        self.update()

    def set_andando(self, andando: bool) -> None:
        self.andando = andando
        self.update()

    def avancar_quadro(self) -> None:
        self.quadro = 1 - self.quadro
        if self.andando or self.pose == "autografando":
            self.update()

    def _pixel(self, painter: QPainter, x: int, y: int, cor: str) -> None:
        escala = self.PIXEL
        painter.fillRect(
            QRectF(x * escala, y * escala, escala, escala), QColor(cor)
        )

    def _faixa(
        self, painter: QPainter, y: int, inicio: int, fim: int, cor: str
    ) -> None:
        for x in range(inicio, fim + 1):
            self._pixel(painter, x, y, cor)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        paleta = self.PALETAS[self.aparencia]
        pele = paleta["pele"]
        cabelo = paleta["cabelo"]
        camisa = paleta["camisa"]
        detalhe = paleta["detalhe"]
        calca = paleta["calca"]

        for y, inicio, fim in (
            (0, 6, 10),
            (1, 4, 12),
            (2, 3, 13),
            (3, 3, 13),
        ):
            self._faixa(painter, y, inicio, fim, cabelo)

        if self.estilo_cabelo == 2:
            self._faixa(painter, 3, 13, 15, cabelo)
            self._faixa(painter, 4, 14, 15, cabelo)
            self._faixa(painter, 5, 14, 15, cabelo)
        elif self.estilo_cabelo == 3:
            self._faixa(painter, 1, 2, 4, cabelo)
            self._faixa(painter, 1, 12, 14, cabelo)
            self._faixa(painter, 2, 1, 3, cabelo)
            self._faixa(painter, 2, 13, 15, cabelo)

        for y in range(4, 12):
            self._faixa(painter, y, 4, 12, pele)
        self._pixel(painter, 3, 7, pele)
        self._pixel(painter, 13, 7, pele)

        if self.estilo_cabelo in (1, 3):
            for y in range(4, 15):
                self._pixel(painter, 3, y, cabelo)
                self._pixel(painter, 13, y, cabelo)
        else:
            for y in range(4, 9):
                self._pixel(painter, 3, y, cabelo)
                self._pixel(painter, 13, y, cabelo)
        if self.estilo_cabelo == 0:
            self._faixa(painter, 4, 5, 7, cabelo)
            self._faixa(painter, 5, 9, 11, cabelo)
        elif self.estilo_cabelo == 1:
            self._faixa(painter, 4, 5, 11, cabelo)
        elif self.estilo_cabelo == 2:
            self._faixa(painter, 4, 5, 9, cabelo)
            self._faixa(painter, 5, 10, 12, cabelo)
        else:
            self._faixa(painter, 4, 4, 10, cabelo)
            self._pixel(painter, 11, 5, cabelo)

        for x in (6, 10):
            self._pixel(painter, x, 6, cabelo)
            self._pixel(painter, x, 7, "#fff5df")
            self._pixel(painter, x, 8, "#24243d")
        self._pixel(painter, 8, 9, "#c77e69")
        self._pixel(painter, 7, 10, "#743d4b")
        self._pixel(painter, 8, 10, "#743d4b")
        self._pixel(painter, 9, 10, "#743d4b")
        self._pixel(painter, 5, 9, "#e99b86")
        self._pixel(painter, 11, 9, "#e99b86")
        if self.estilo_cabelo == 1:
            for x in (5, 7, 9, 11):
                self._pixel(painter, x, 7, "#382b42")
            self._pixel(painter, 8, 7, "#382b42")
        elif self.estilo_cabelo == 3:
            self._pixel(painter, 5, 9, "#8c5749")
            self._pixel(painter, 11, 9, "#8c5749")

        self._faixa(painter, 12, 7, 9, pele)
        self._faixa(painter, 13, 6, 10, camisa)
        for y in range(14, 19):
            self._faixa(painter, y, 4, 12, camisa)

        deslocamento_braco = self.quadro if self.andando else 0
        for y in range(14, 19):
            self._pixel(painter, 3, y + deslocamento_braco, pele)
            self._pixel(painter, 13, y - deslocamento_braco, pele)
        self._pixel(painter, 4, 15, detalhe)
        self._pixel(painter, 12, 15, detalhe)
        self._faixa(painter, 16, 7, 9, detalhe)

        if self.papel == "autor":
            self._faixa(painter, 19, 5, 11, calca)
            self._faixa(painter, 20, 6, 12, calca)
            self._faixa(painter, 21, 9, 13, paleta["sapato"])
            self._pixel(painter, 13, 15, pele)
            self._pixel(painter, 14, 15, pele)
            caneta_y = 16 + self.quadro
            self._pixel(painter, 15, caneta_y, "#332b42")
            self._pixel(painter, 14, caneta_y, detalhe)
            return

        if self.pose == "lendo":
            self._faixa(painter, 15, 13, 15, pele)
            self._faixa(painter, 16, 14, 15, "#584c7b")
            self._faixa(painter, 17, 14, 15, "#fff2c8")
            self._faixa(painter, 18, 14, 15, "#fff2c8")
            self._pixel(painter, 15, 17, "#ce6c78")
        else:
            perna_esquerda = -self.quadro if self.andando else 0
            perna_direita = self.quadro if self.andando else 0
            for y in (19, 20, 21):
                self._pixel(painter, 6 + perna_esquerda, y, calca)
                self._pixel(painter, 7 + perna_esquerda, y, calca)
                self._pixel(painter, 10 + perna_direita, y, calca)
                self._pixel(painter, 11 + perna_direita, y, calca)
            self._faixa(painter, 22, 5 + perna_esquerda, 7 + perna_esquerda, paleta["sapato"])
            self._faixa(painter, 22, 10 + perna_direita, 12 + perna_direita, paleta["sapato"])


class CenarioAutografos(QGraphicsScene):
    MAX_FAS_VISIVEIS = 5
    X_FRENTE = 500
    PASSO_FILA = 95
    Y_FILA = 235
    X_ASSINATURA = 590

    def __init__(self) -> None:
        super().__init__(0, 0, 1260, 480)
        self._personagens_fila: dict[int, PersonagemPixel] = {}
        self._personagens_leitores: dict[int, PersonagemPixel] = {}
        self._animacoes_movimento: dict[PersonagemPixel, QPropertyAnimation] = {}
        self._grupos_leitura: dict[int, QSequentialAnimationGroup] = {}
        self._id_assinando: int | None = None
        self._itens_assinaturas: list[QGraphicsSimpleTextItem] = []
        self._desenhar_cenario()

        self.autor = PersonagemPixel(4, papel="autor")
        self.autor.setPos(675, 164)
        self.addItem(self.autor)

        self._relogio = QTimer(self)
        self._relogio.timeout.connect(self._avancar_animacoes)
        self._relogio.start(150)

    def _retangulo(
        self, x: int, y: int, largura: int, altura: int, cor: str
    ) -> None:
        self.addRect(
            x,
            y,
            largura,
            altura,
            Qt.PenStyle.NoPen,
            QBrush(cor),
        )

    def _texto(
        self,
        texto: str,
        x: int,
        y: int,
        cor: str = "#f8e7a1",
        tamanho: int = 12,
    ) -> QGraphicsSimpleTextItem:
        item = self.addSimpleText(
            texto, QFont("Consolas", tamanho, QFont.Weight.Bold)
        )
        item.setBrush(QBrush(cor))
        item.setPos(x, y)
        return item

    def _desenhar_cenario(self) -> None:
        self._retangulo(0, 0, 1260, 480, "#282447")
        for x in range(0, 1260, 40):
            self._retangulo(x, 82, 20, 7, "#37345c")
            self._retangulo(x + 18, 184, 22, 7, "#37345c")

        self._retangulo(0, 365, 1260, 115, "#583e50")
        for x in range(0, 1260, 48):
            self._retangulo(x, 365, 2, 115, "#76505a")
        self._retangulo(0, 365, 1260, 4, "#e6a858")

        for x in range(80, 1190, 48):
            self._retangulo(x, 40, 8, 8, "#f8d875")
            self._retangulo(x + 8, 48, 8, 8, "#e98668")      
        self._texto("LIVRARIA PIXEL - EVENTO DE LANCAMENTO", 405, 58, "#c7c5e8", 15)

        self._texto("FILA DE FAS", 106, 175, "#a8d7e8", 12)
        self._retangulo(90, 351, 455, 3, "#edbf61")
        for x in (180, 280, 380, 480):
            self._retangulo(x, 347, 5, 10, "#edbf61")
            self._retangulo(x + 5, 352, 5, 5, "#edbf61")
        self._item_fila = self._texto("FILA: 0", 105, 192, "#fff0c2", 10)
        self._item_estado_fa = self._texto(
            "FÃ DA VEZ: AGUARDANDO AUTÓGRAFO",
            105,
            211,
            "#f5c66a",
            13,
        )

        self._texto("AUTOR", 695, 100, "#a8d7e8", 12)
        self._retangulo(687, 205, 62, 84, "#76505a")
        self._retangulo(677, 201, 82, 10, "#e6a858")
        self._retangulo(695, 230, 10, 37, "#c78150")
        self._retangulo(737, 230, 10, 37, "#c78150")
        self._retangulo(633, 285, 193, 16, "#d18a4d")
        self._retangulo(646, 301, 14, 54, "#9a5d40")
        self._retangulo(797, 301, 14, 54, "#9a5d40")
        self._retangulo(614, 273, 52, 9, "#fff5d6")
        self._texto("LIVRO DE AUTOGRAFOS", 605, 319, "#fff0c2", 9)
        self._item_estado_escritor = self._texto(
            "ESCRITOR: LIVRE", 663, 371, "#9fe0a2", 12
        )

        self._retangulo(890, 93, 330, 268, "#17172c")
        self._retangulo(898, 101, 314, 252, "#e4c78c")
        self._retangulo(905, 108, 300, 29, "#65466b")
        self._texto("LISTA DE AUTOGRAFOS", 925, 114, "#fff0b0", 12)
        self._texto("CONSULTA COMPARTILHADA", 919, 143, "#59485e", 9)
        self._item_estado_leitor = self._texto(
            "LEITOR: LIVRE", 918, 293, "#385d68", 12
        )
        self._retangulo(912, 308, 284, 2, "#b69a69")
        self._item_total = self._texto("TOTAL: 0", 918, 315, "#385d68", 12)
        self._item_leitores = self._texto(
            "LEITORES ATIVOS: 0", 918, 335, "#385d68", 12
        )
        self._item_anteriores: QGraphicsSimpleTextItem | None = None

    def _avancar_animacoes(self) -> None:
        self.autor.avancar_quadro()
        for personagem in (
            *self._personagens_fila.values(),
            *self._personagens_leitores.values(),
        ):
            personagem.avancar_quadro()

    def atualizar_contagem_fila(self, quantidade: int) -> None:
        fora_da_cena = max(0, quantidade - self.MAX_FAS_VISIVEIS)
        texto = f"FILA: {quantidade}"
        if fora_da_cena:
            texto += f"  (+{fora_da_cena} aguardando)"
        self._item_fila.setText(texto)

    def atualizar_leitores(self, quantidade: int) -> None:
        self._item_leitores.setText(f"LEITORES ATIVOS: {quantidade}")

    def atualizar_estado_fa(self, texto: str, cor: str) -> None:
        self._item_estado_fa.setText(texto)
        self._item_estado_fa.setBrush(QBrush(cor))

    def atualizar_estado_leitor(self, texto: str, cor: str) -> None:
        self._item_estado_leitor.setText(texto)
        self._item_estado_leitor.setBrush(QBrush(cor))

    def atualizar_lista(self, autografos: tuple[str, ...]) -> None:
        for item in self._itens_assinaturas:
            self.removeItem(item)
        self._itens_assinaturas.clear()
        if self._item_anteriores is not None:
            self.removeItem(self._item_anteriores)
            self._item_anteriores = None

        anteriores = max(0, len(autografos) - 6)
        if anteriores:
            self._item_anteriores = self._texto(
                f"... {anteriores} autografos anteriores",
                921,
                163,
                "#68586a",
                9,
            )

        recentes = autografos[-6:]
        for indice, nome in enumerate(recentes):
            item = self._texto(
                f"OK  {nome}",
                921,
                164 + (indice + bool(anteriores)) * 19,
                "#256044",
                10,
            )
            self._itens_assinaturas.append(item)
        self._item_total.setText(f"TOTAL: {len(autografos)}")

    def sincronizar_fila(
        self,
        fila: list[Fa],
        animar: bool = False,
        atendido_id: int | None = None,
    ) -> None:
        visiveis = fila[: self.MAX_FAS_VISIVEIS]
        ids_visiveis = {fa.id for fa in visiveis}

        for fa_id in tuple(self._personagens_fila):
            if fa_id in ids_visiveis or fa_id == self._id_assinando:
                continue
            personagem = self._personagens_fila.pop(fa_id)
            if fa_id == atendido_id and animar:
                personagem.set_pose("andando")
                self._mover(
                    personagem,
                    835,
                    self.Y_FILA,
                    520,
                    lambda personagem=personagem: self._remover_personagem(
                        personagem
                    ),
                )
            else:
                self.removeItem(personagem)

        for indice, fa in enumerate(visiveis):
            personagem = self._personagens_fila.get(fa.id)
            destino_x = self.X_FRENTE - indice * self.PASSO_FILA
            if personagem is None:
                personagem = PersonagemPixel(fa.aparencia, fa.nome)
                self._personagens_fila[fa.id] = personagem
                self.addItem(personagem)
                if animar:
                    personagem.setPos(62, self.Y_FILA)
                    personagem.set_pose("andando")
                    self._mover(
                        personagem,
                        destino_x,
                        self.Y_FILA,
                        650,
                    )
                else:
                    personagem.setPos(destino_x, self.Y_FILA)
            elif fa.id != self._id_assinando:
                if animar and abs(personagem.pos().x() - destino_x) > 1:
                    personagem.set_pose("andando")
                    self._mover(
                        personagem,
                        destino_x,
                        self.Y_FILA,
                        620,
                    )
                else:
                    personagem.setPos(destino_x, self.Y_FILA)

        self.atualizar_contagem_fila(len(fila))

    def iniciar_autografo(self, fa_id: int, nome: str) -> None:
        personagem = self._personagens_fila.get(fa_id)
        if personagem is None:
            raise RuntimeError("O proximo fa nao esta visivel na fila.")

        self._id_assinando = fa_id
        personagem.set_pose("andando")
        self.autor.set_pose("autografando")
        self.atualizar_estado_fa(
            f"{nome.upper()}: SENDO AUTOGRAFADO", "#f17b61"
        )
        self.atualizar_escritor("AUTOGRAFANDO", "#f17b61")
        self._mover(
            personagem,
            self.X_ASSINATURA,
            self.Y_FILA,
            520,
            lambda personagem=personagem: personagem.set_pose("recebendo"),
        )

    def finalizar_autografo(
        self,
        fa_id: int,
        fila: list[Fa],
        autografos: tuple[str, ...],
    ) -> None:
        self.autor.set_pose("parado")
        self.atualizar_escritor("LIVRE", "#9fe0a2")
        self.atualizar_lista(autografos)
        self._id_assinando = None
        self.sincronizar_fila(fila, animar=True, atendido_id=fa_id)

    def iniciar_consulta(self, leitor_id: int, duracao_segundos: int) -> None:
        personagem = PersonagemPixel(leitor_id + 2, papel="leitor")
        personagem.setPos(1070, 238 + (leitor_id % 2) * 18)
        personagem.set_pose("andando")
        self._personagens_leitores[leitor_id] = personagem
        self.addItem(personagem)

        tempo_deslocamento = 500
        tempo_total = max(2000, duracao_segundos * 1000)
        chegada = QPropertyAnimation(personagem, b"pos")
        chegada.setDuration(tempo_deslocamento)
        chegada.setStartValue(personagem.pos())
        chegada.setEndValue(QPointF(817, personagem.pos().y()))
        pausa = QPauseAnimation(tempo_total - 2 * tempo_deslocamento)
        saida = QPropertyAnimation(personagem, b"pos")
        saida.setDuration(tempo_deslocamento)
        saida.setStartValue(QPointF(817, personagem.pos().y()))
        saida.setEndValue(QPointF(1070, personagem.pos().y()))

        grupo = QSequentialAnimationGroup(self)
        grupo.addAnimation(chegada)
        grupo.addAnimation(pausa)
        grupo.addAnimation(saida)
        grupo.currentAnimationChanged.connect(
            lambda atual, personagem=personagem, pausa=pausa: self._mudar_pose_leitor(
                personagem, atual, pausa
            )
        )
        grupo.finished.connect(
            lambda leitor_id=leitor_id, personagem=personagem: self._fim_consulta_visual(
                leitor_id, personagem
            )
        )
        self._grupos_leitura[leitor_id] = grupo
        grupo.start()

    @staticmethod
    def _mudar_pose_leitor(
        personagem: PersonagemPixel,
        animacao_atual,
        pausa: QPauseAnimation,
    ) -> None:
        lendo = animacao_atual is pausa
        personagem.set_pose("lendo" if lendo else "andando")
        personagem.set_andando(not lendo)

    def _fim_consulta_visual(
        self, leitor_id: int, personagem: PersonagemPixel
    ) -> None:
        self._personagens_leitores.pop(leitor_id, None)
        self.removeItem(personagem)
        grupo = self._grupos_leitura.pop(leitor_id, None)
        if grupo is not None:
            grupo.deleteLater()

    def atualizar_escritor(self, estado: str, cor: str) -> None:
        self._item_estado_escritor.setText(f"ESCRITOR: {estado}")
        self._item_estado_escritor.setBrush(QBrush(cor))

    def _mover(
        self,
        personagem: PersonagemPixel,
        x: float,
        y: float,
        duracao: int,
        ao_terminar=None,
    ) -> None:
        animacao_anterior = self._animacoes_movimento.pop(personagem, None)
        if animacao_anterior is not None:
            animacao_anterior.stop()
            animacao_anterior.deleteLater()

        animacao = QPropertyAnimation(personagem, b"pos", self)
        animacao.setDuration(duracao)
        animacao.setStartValue(personagem.pos())
        animacao.setEndValue(QPointF(x, y))
        animacao.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animacoes_movimento[personagem] = animacao

        def concluir() -> None:
            if self._animacoes_movimento.get(personagem) is animacao:
                self._animacoes_movimento.pop(personagem, None)
            personagem.set_andando(False)
            animacao.deleteLater()
            if ao_terminar is not None:
                ao_terminar()

        personagem.set_andando(True)
        animacao.finished.connect(concluir)
        animacao.start()

    def _remover_personagem(self, personagem: PersonagemPixel) -> None:
        animacao = self._animacoes_movimento.pop(personagem, None)
        if animacao is not None:
            animacao.deleteLater()
        self.removeItem(personagem)


class PixelView(QGraphicsView):
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.scene() is not None:
            self.fitInView(
                self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )


class JanelaAutografos(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.trava = TravaLeitoresEscritores()
        self.autografos: list[str] = []
        self._lista_exibida: tuple[str, ...] = ()
        self.fila: deque[Fa] = deque()
        self._proximo_fa_id = 1
        self._proximo_leitor_id = 1
        self._numero_leitores_ativos = 0
        self._leitores_aguardando: set[int] = set()
        self._limite_leitores: int | None = None
        self._workers: set[QThread] = set()
        self._escritor_ocupado = False

        self.setWindowTitle("Noite de autografos - Leitores e escritores")
        self.setMinimumSize(1040, 760)
        self.setStyleSheet(
            """
            QWidget {
                background: #211e39;
                color: #f2e8c9;
                font-family: Consolas, monospace;
                font-size: 13px;
            }
            QLabel#titulo { color: #ffe28a; font-size: 22px; font-weight: bold; }
            QLabel#subtitulo { color: #c0badc; }
            QLabel#estado {
                background: #312944;
                color: #ffe28a;
                border: 3px solid #e6a858;
                padding: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QGroupBox {
                color: #ffe28a;
                border: 2px solid #6d5b79;
                margin-top: 8px;
                padding: 7px;
                font-size: 14px;
                font-weight: bold;
            }
            QSpinBox {
                background: #17172c;
                color: #fff3d4;
                border: 2px solid #6d5b79;
                padding: 5px;
                min-width: 90px;
                font-size: 15px;
            }
            QPushButton {
                background: #a34f68;
                color: #fff3d4;
                border: 3px solid #e6a858;
                padding: 10px 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #bd6175; }
            QPushButton:disabled {
                background: #51475d;
                color: #aaa1ad;
                border-color: #786779;
            }
            QTextEdit {
                background: #17172c;
                color: #d7edcf;
                border: 3px solid #6d5b79;
                padding: 7px;
                selection-background-color: #80506c;
            }
            """
        )

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(14)

        area_evento = QVBoxLayout()
        area_evento.setSpacing(10)
        layout.addLayout(area_evento, stretch=1)

        titulo = QLabel("NOITE DE AUTOGRAFOS")
        titulo.setObjectName("titulo")
        subtitulo = QLabel(
            "Leitores consultam juntos; o autor atualiza a lista com acesso exclusivo."
        )
        subtitulo.setObjectName("subtitulo")
        area_evento.addWidget(titulo)
        area_evento.addWidget(subtitulo)

        painel_lateral = QWidget()
        painel_lateral.setFixedWidth(300)
        controles_laterais = QVBoxLayout(painel_lateral)
        controles_laterais.setContentsMargins(0, 0, 0, 0)
        controles_laterais.setSpacing(10)

        painel_tempos = QGroupBox("DURAÇÃO DAS AÇÕES")
        controles_tempos = QVBoxLayout(painel_tempos)
        controles_tempos.addWidget(QLabel("Consulta da lista:"))
        self.tempo_leitura = QSpinBox()
        self.tempo_leitura.setRange(2, 30)
        self.tempo_leitura.setValue(5)
        self.tempo_leitura.setSuffix(" s")
        self.tempo_leitura.setToolTip(
            "Tempo em que os leitores mantêm a lista aberta."
        )
        controles_tempos.addWidget(self.tempo_leitura)
        controles_tempos.addWidget(QLabel("Autógrafo:"))
        self.tempo_escrita = QSpinBox()
        self.tempo_escrita.setRange(2, 30)
        self.tempo_escrita.setValue(4)
        self.tempo_escrita.setSuffix(" s")
        self.tempo_escrita.setToolTip(
            "Tempo em que o autor mantém a lista bloqueada para escrever."
        )
        controles_tempos.addWidget(self.tempo_escrita)
        controles_laterais.addWidget(painel_tempos)

        painel_leitores = QGroupBox("CONTROLE DE LEITORES")
        controles_leitores = QVBoxLayout(painel_leitores)
        linha_limite = QHBoxLayout()
        linha_limite.addWidget(QLabel("Máximo simultâneo:"))
        self.limite_leitores = QSpinBox()
        self.limite_leitores.setRange(1, 3)
        self.limite_leitores.setValue(2)
        self.limite_leitores.setToolTip(
            "Limita a quantidade de consultas simultâneas entre 1 e 3."
        )
        linha_limite.addWidget(self.limite_leitores)
        controles_leitores.addLayout(linha_limite)
        self.botao_limitar = QPushButton("APLICAR LIMITE")
        self.botao_ilimitado = QPushButton("SEM LIMITE")
        self.botao_musica = QPushButton("MÚSICA: LIGADA")
        self.botao_limitar.clicked.connect(self._aplicar_limite_leitores)
        self.botao_ilimitado.clicked.connect(self._liberar_limite_leitores)
        self.botao_musica.clicked.connect(self._alternar_musica)
        controles_leitores.addWidget(self.botao_limitar)
        controles_leitores.addWidget(self.botao_ilimitado)
        controles_leitores.addWidget(self.botao_musica)
        controles_laterais.addWidget(painel_leitores)

        self.cenario = CenarioAutografos()
        self.visao = PixelView(self.cenario)
        self.visao.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.visao.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.visao.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.visao.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.visao.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.visao.setMinimumHeight(380)
        self.visao.setStyleSheet("border: 3px solid #6d5b79;")
        area_evento.addWidget(self.visao, stretch=1)

        painel_acoes = QGroupBox("AÇÕES DO EVENTO")
        botoes = QVBoxLayout(painel_acoes)
        self.botao_adicionar = QPushButton("ADICIONAR FÃ À FILA")
        self.botao_autografo = QPushButton("AUTOGRAFAR PRÓXIMO")
        self.botao_consulta = QPushButton("CONSULTAR LISTA")
        self.botao_adicionar.clicked.connect(self.adicionar_fa)
        self.botao_autografo.clicked.connect(self.autografar_proximo)
        self.botao_consulta.clicked.connect(self.consultar_lista)
        botoes.addWidget(self.botao_adicionar)
        botoes.addWidget(self.botao_autografo)
        botoes.addWidget(self.botao_consulta)
        controles_laterais.addWidget(painel_acoes)
        controles_laterais.addStretch(1)
        layout.addWidget(painel_lateral)

        self.estado = QLabel("Evento aberto. Os fãs aguardam na fila.")
        self.estado.setObjectName("estado")
        self.estado.setWordWrap(True)
        area_evento.addWidget(self.estado)
        self.registro = QTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMaximumHeight(95)
        self.registro.setPlaceholderText("As ações do evento aparecerão aqui.")
        area_evento.addWidget(self.registro)

        self.setCentralWidget(central)
        self.setMinimumSize(1200, 760)
        self.resize(1480, 850)

        self.audio = AudioEvento()
        self.audio.erro.connect(
            lambda mensagem: self._registrar(mensagem, "#ff6262")
        )
        if self.audio.aviso:
            self._registrar(self.audio.aviso, "#ff6262")
        else:
            self.audio.definir_musica(True)
        estado_musica = "LIGADA" if self.audio.musica_ativa else "DESLIGADA"
        self.botao_musica.setText(f"MÚSICA: {estado_musica}")
        self.botao_musica.setEnabled(self.audio.disponivel)
        botoes_com_som = (
            self.botao_adicionar,
            self.botao_autografo,
            self.botao_consulta,
            self.botao_limitar,
            self.botao_ilimitado,
            self.botao_musica,
        )
        for botao in botoes_com_som:
            botao.clicked.connect(lambda: self.audio.tocar("clique"))

        for _ in range(4):
            self.adicionar_fa(animar=False, registrar=False)
        self._registrar("Evento iniciado: quatro fãs aguardam o autógrafo.")

    def _registrar(self, mensagem: str, cor: str = "#d7edcf") -> None:
        cursor = self.registro.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        formato = self.registro.currentCharFormat()
        formato.setForeground(QColor(cor))
        cursor.insertText(mensagem + "\n", formato)
        self.registro.setTextCursor(cursor)
        self.registro.ensureCursorVisible()

    def _acompanhar_worker(self, worker: QThread) -> None:
        self._workers.add(worker)
        worker.finished.connect(self._remover_worker)
        worker.start()

    def _remover_worker(self) -> None:
        worker = self.sender()
        if isinstance(worker, QThread):
            self._workers.discard(worker)
            worker.deleteLater()

    def adicionar_fa(self, animar: bool = True, registrar: bool = True) -> None:
        fa = Fa(
            id=self._proximo_fa_id,
            nome=f"Fã {self._proximo_fa_id}",
            aparencia=self._proximo_fa_id - 1,
        )
        self._proximo_fa_id += 1
        self.fila.append(fa)
        self.cenario.sincronizar_fila(list(self.fila), animar=animar)
        if registrar:
            self.audio.tocar("chegada")
        self.botao_autografo.setEnabled(
            bool(self.fila) and not self._escritor_ocupado
        )
        if len(self.fila) == 1 and not self._escritor_ocupado:
            self.cenario.atualizar_estado_fa(
                f"{fa.nome.upper()}: AGUARDANDO PARA SER AUTOGRAFADO",
                "#f5c66a",
            )
        if registrar:
            self._registrar(f"{fa.nome} entrou no fim da fila.")
        self._atualizar_estado()

    def _aplicar_limite_leitores(self) -> None:
        self._limite_leitores = self.limite_leitores.value()
        self._registrar(
            f"Limite aplicado: até {self._limite_leitores} leitor(es) "
            "simultâneo(s)."
        )

    def _liberar_limite_leitores(self) -> None:
        self._limite_leitores = None
        self._registrar("Limite removido: consultas sem limite configurado.")

    def _alternar_musica(self) -> None:
        ativa = self.audio.definir_musica(not self.audio.musica_ativa)
        estado = "LIGADA" if ativa else "DESLIGADA"
        self.botao_musica.setText(f"MÚSICA: {estado}")

    def consultar_lista(self) -> None:
        quantidade_reservada = (
            self._numero_leitores_ativos + len(self._leitores_aguardando)
        )
        if (
            self._limite_leitores is not None
            and quantidade_reservada >= self._limite_leitores
        ):
            self._registrar(
                "Máximo de Leitores alcançado. Aguarde ao menos 1 leitor "
                "terminar a consulta.",
                "#ff6262",
            )
            return

        leitor_id = self._proximo_leitor_id
        self._proximo_leitor_id += 1
        duracao = self.tempo_leitura.value()
        self._leitores_aguardando.add(leitor_id)
        self.cenario.atualizar_estado_leitor(
            f"LEITOR {leitor_id}: AGUARDANDO ACESSO",
            "#f5c66a",
        )
        self.estado.setText(
            f"LEITOR {leitor_id}: AGUARDANDO ACESSO À LISTA"
        )
        worker = LeitorWorker(
            leitor_id, self.trava, self.autografos, duracao
        )
        worker.mensagem.connect(self._registrar)
        worker.entrou.connect(self._leitor_entrou)
        worker.consulta_concluida.connect(self._consulta_concluida)
        self._acompanhar_worker(worker)

    def _leitor_entrou(self, leitor_id: int, duracao: int) -> None:
        self._leitores_aguardando.discard(leitor_id)
        self._numero_leitores_ativos += 1
        self.audio.tocar("passos")
        self.audio.tocar("consulta")
        self.cenario.atualizar_leitores(self._numero_leitores_ativos)
        self.cenario.iniciar_consulta(leitor_id, duracao)
        self.cenario.atualizar_estado_leitor(
            f"LEITOR {leitor_id}: CONSULTANDO LISTA",
            "#256044",
        )
        if self._leitores_aguardando:
            self.estado.setText(
                f"LEITOR {min(self._leitores_aguardando)}: "
                "AGUARDANDO ACESSO À LISTA"
            )
        else:
            self.estado.setText(
                f"LEITOR {leitor_id}: CONSULTANDO A LISTA"
            )

    def _consulta_concluida(
        self, leitor_id: int, autografos: tuple[str, ...]
    ) -> None:
        self._leitores_aguardando.discard(leitor_id)
        if len(autografos) >= len(self._lista_exibida):
            self._lista_exibida = autografos
        self.cenario.atualizar_lista(self._lista_exibida)
        self._numero_leitores_ativos = max(0, self._numero_leitores_ativos - 1)
        self.cenario.atualizar_leitores(self._numero_leitores_ativos)
        if self._leitores_aguardando:
            self.cenario.atualizar_estado_leitor(
                f"LEITOR {min(self._leitores_aguardando)}: AGUARDANDO ACESSO",
                "#f5c66a",
            )
        elif self._numero_leitores_ativos:
            self.cenario.atualizar_estado_leitor(
                f"{self._numero_leitores_ativos} LEITOR(ES): CONSULTANDO",
                "#256044",
            )
        else:
            self.cenario.atualizar_estado_leitor(
                "LEITOR: CONSULTA CONCLUÍDA",
                "#385d68",
            )
        conteudo = (
            ", ".join(autografos)
            if autografos
            else "a lista ainda esta vazia"
        )
        self._registrar(f"Consulta concluída: {conteudo}.")
        self._atualizar_estado()

    def autografar_proximo(self) -> None:
        if self._escritor_ocupado or not self.fila:
            return

        fa = self.fila[0]
        self._escritor_ocupado = True
        self.botao_autografo.setEnabled(False)
        self.cenario.atualizar_estado_fa(
            f"{fa.nome.upper()}: AGUARDANDO PARA SER AUTOGRAFADO",
            "#f5c66a",
        )
        self.cenario.atualizar_escritor("AGUARDANDO", "#f5c66a")
        self.estado.setText(f"O autor aguarda para autografar para {fa.nome}.")

        worker = AutorWorker(
            fa,
            self.trava,
            self.autografos,
            self.tempo_escrita.value(),
        )
        worker.mensagem.connect(self._registrar)
        worker.comecou_a_assinar.connect(self._autor_comecou)
        worker.autografo_concluido.connect(self._autografo_concluido)
        self._acompanhar_worker(worker)

    def _autor_comecou(self, fa_id: int, nome: str) -> None:
        self.audio.iniciar_escrita()
        self.cenario.iniciar_autografo(fa_id, nome)
        if self._leitores_aguardando:
            self.estado.setText(
                f"LEITOR {min(self._leitores_aguardando)}: "
                "AGUARDANDO ACESSO À LISTA"
            )
        else:
            self.estado.setText(f"O autor está autografando para {nome}.")

    def _autografo_concluido(
        self,
        fa_id: int,
        nome: str,
        autografos: tuple[str, ...],
    ) -> None:
        if not self.fila or self.fila[0].id != fa_id:
            raise RuntimeError("A ordem da fila mudou durante o autógrafo.")

        self.audio.parar_escrita()
        self.fila.popleft()
        self._escritor_ocupado = False
        self._lista_exibida = autografos
        self.cenario.finalizar_autografo(
            fa_id, list(self.fila), self._lista_exibida
        )
        if self.fila:
            self.cenario.atualizar_estado_fa(
                f"{self.fila[0].nome.upper()}: AGUARDANDO PARA SER AUTOGRAFADO",
                "#f5c66a",
            )
        else:
            self.cenario.atualizar_estado_fa(
                "FILA VAZIA: ADICIONE UM FÃ",
                "#c7c5e8",
            )
        self._registrar(
            f"{nome} recebeu o autógrafo. Total: {len(autografos)}."
        )
        self.botao_autografo.setEnabled(bool(self.fila))
        self._atualizar_estado()

    def _atualizar_estado(self) -> None:
        if self._escritor_ocupado:
            return
        if self._leitores_aguardando:
            self.estado.setText(
                f"LEITOR {min(self._leitores_aguardando)}: "
                "AGUARDANDO ACESSO À LISTA"
            )
            return
        if self._numero_leitores_ativos:
            self.estado.setText(
                f"{self._numero_leitores_ativos} leitor(es) consultando; "
                f"{len(self.autografos)} autógrafo(s) na lista."
            )
        elif self.fila:
            self.estado.setText(
                f"{self.fila[0].nome.upper()}: AGUARDANDO PARA SER AUTOGRAFADO"
            )
        else:
            self.estado.setText("Fila vazia. Adicione um fã para continuar.")

    def closeEvent(self, event: QCloseEvent) -> None:
        if any(worker.isRunning() for worker in self._workers):
            self.estado.setText("Aguarde as consultas e o autógrafo terminarem.")
            event.ignore()
            return
        self.audio.encerrar()
        event.accept()


def main() -> None:
    aplicativo = QApplication(sys.argv)
    janela = JanelaAutografos()
    janela.show()
    sys.exit(aplicativo.exec())


if __name__ == "__main__":
    main()
