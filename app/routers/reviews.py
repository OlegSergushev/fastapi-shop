from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.reviews import Review as ReviewModel
from app.models.products import Product as ProductModel
from app.models.users import User as UserModel
from app.schemas import Reviews as ReviewsSchema, ReviewCreate
from app.db_depends import get_async_db
from app.auth import get_current_user

# Создаём маршрутизатор для отзывов
router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
)


@router.get("/", response_model=list[ReviewsSchema])
async def get_all_reviews(db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает список всех отзывов.
    """
    reviews_result = await db.scalars(
        select(ReviewModel).where(
            ReviewModel.is_active == True)
    )

    return reviews_result.all()


@router.get("/products/{product_id}/reviews", response_model=list[ReviewsSchema])
async def get_reviews_by_product(product_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает список отзывов о товаре по его ID.
    """

    # Проверяем существует ли товар
    result = await db.scalars(
        select(ProductModel).where(
            ProductModel.id == product_id,
            ProductModel.is_active == True
        )
    )
    product = result.first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or inactive")

    # Получаем отзывы
    result = await db.scalars(
        select(ReviewModel).where(
            ReviewModel.product_id == product_id,
            ReviewModel.is_active == True
        )
        .order_by(ReviewModel.comment_date.desc())
    )

    return result.all()


@router.post("/", response_model=ReviewsSchema, status_code=status.HTTP_201_CREATED)
async def create_reviews(review: ReviewCreate,
                         db: AsyncSession = Depends(get_async_db),
                         current_user: UserModel = Depends(get_current_user)):

    """
    Создаёт новый отзыв и пересчитывает рейтинг продукта.
    """

    # Проверка роли
    if current_user.role != "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only users with role 'buyer' can add reviews"
        )

    # Проверка существования продукта
    result = await db.scalars(
        select(ProductModel).where(
            ProductModel.id == review.product_id,
            ProductModel.is_active == True))
    product = result.first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or inactive")

    # Проверка диапазона оценки
    if review.grade < 1 or review.grade > 5:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Grade out of the range 1–5")

    # Создаем новый комментарий
    new_review = ReviewModel(
        comment=review.comment,
        grade=review.grade,
        user_id=current_user.id,
        product_id=review.product_id,
        is_active=True,
    )
    db.add(new_review)
    await db.commit()
    await db.refresh(new_review)

    # Обновляем рейтинг товара
    result = await db.execute(
        select(func.avg(ReviewModel.grade)).where(
            ReviewModel.product_id == review.product_id,
            ReviewModel.is_active == True)
    )
    avg_rating = result.scalar() or 0.0
    product = await db.get(ProductModel, review.product_id)
    product.rating = avg_rating
    await db.commit()

    return new_review


@router.delete("/{review_id}", status_code=status.HTTP_200_OK)
async def delete_reviews(review_id: int,
                         db: AsyncSession = Depends(get_async_db),
                         current_user: UserModel = Depends(get_current_user)):
    """
    Логически удаляет комментарий по его ID, и пересчитывает рейтинг продукта.
    """

    # Проверка роли
    if current_user.role != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete reviews")

    # Проверяем, что отзыв существует и активен
    result = await db.scalars(select(ReviewModel).where(
        ReviewModel.id == review_id,
        ReviewModel.is_active == True)
    )
    review = result.first()
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reviews not found or inactive")

    # Мягкое удаление
    await db.execute(update(ReviewModel).where(ReviewModel.id == review_id).values(is_active=False))
    await db.commit()
    await db.refresh(review)

    # Обновляем рейтинг товара
    result = await db.execute(
        select(func.avg(ReviewModel.grade)).where(
            ReviewModel.product_id == review.product_id,
            ReviewModel.is_active == True)
    )
    avg_rating = result.scalar() or 0.0
    product = await db.get(ProductModel, review.product_id)
    product.rating = avg_rating
    await db.commit()
    return {"message": "Review deleted"}
